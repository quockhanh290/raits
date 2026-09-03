## Task: RAITS — IS Optimization → WFO → OOS Preparation
Status: IN PROGRESS

---
## Sub-task: Trust Audit (DONE 2026-07-05)
Status: DONE

### Completed
- [x] STEP 1+2: Full claim inventory + TRACEABLE/SUSPECT/WRONG classification
- [x] STEP 3 — bootstrap_strategy.py committed: re-measured all 9 strategy p-values from results_20260624_135619.pkl
      All 9 verdicts confirmed (FADE/GAP_FILL/VWAP_MR = NO EDGE; TF/ORB/PE_SHORT/STRESS_ORB = CONFIRMED; STRESS_MID/GF_SHORT = BORDERLINE)
- [x] STEP 3 — hmm_annual_convergence.py committed: re-measured 4 scenarios; 6/6 year-ends converge
      Tables match HMM_ANNUAL_CONVERGENCE_AUDIT.md exactly; "3/6 fail" claim definitively WRONG
- [x] STEP 4 — TRUST_AUDIT.md written: full classification table + run commands + outstanding gaps
- [x] STEP 3 — hmm_stability_measure.py committed + run (n_init=10, production): Parts A/B/C fully measured
      Part A: churn 1.1% (claimed 1.8%, overstated by 0.7pp), inversions=0 confirmed
      Part B: agreement 68.6%/67.8% (NOT 98.5%, claim WRONG — 30pp deficit)
      Part C: COVID recall=100% (claimed 91.6%), 2022 bear=88.6% (claimed 80.2%)
      98.5% agreement was fabricated; actual 68% strengthens the case for weekly retrain

- [x] Annual vs weekly head-to-head detection (committed script + run): hmm_annual_vs_weekly_detection.py
      COVID: tied (100%/100%). 2022 bear: annual 100% vs weekly 88.6% (+11.4pp, meets >10pp threshold)
      False-alarm: annual 4.5% vs weekly 10.9% — annual BETTER. Pre-committed criteria MET.
      Decision: weekly remains operating choice (2025 burn cost too high). Annual on table for future.

### Key finding — FINAL
- ALL decisions that affect live trading are on TRACEABLE footing
- Part B "98.5% agreement" claim: WRONG (actual ~68%). Decision to use weekly retrain is STRONGER post-measurement
- "3/6 convergence fail": WRONG (6/6 converge) — disproven by re-measurement
- Annual vs weekly detection: annual materially better on 2022 (+11.4pp, false-alarm also lower). Pre-committed criteria met. Weekly stays (2025 cost); annual is an open question for next retrain decision.

- [x] Artifact check: hmm_retrain_artifact_check.py committed
      Same-method comparison (both Monday carry-forward) + quarterly mechanism analysis.
      Rules out/confirms whether annual's +11.4pp 2022 recall advantage is method artifact
      or structural finding. Run: python raits/raits/scripts/hmm_retrain_artifact_check.py [--fast]
      Output: raits/configs/hmm_retrain_artifact_check.txt

### Files added
TRUST_AUDIT.md, HMM_ANNUAL_CONVERGENCE_AUDIT.md, raits/raits/scripts/bootstrap_strategy.py,
raits/raits/scripts/hmm_annual_convergence.py, raits/raits/scripts/hmm_stability_measure.py,
raits/raits/scripts/hmm_annual_vs_weekly_detection.py, raits/raits/scripts/hmm_retrain_artifact_check.py,
raits/configs/bootstrap_strategy_report.txt, raits/configs/hmm_annual_convergence_report.txt,
raits/configs/hmm_stability_report.txt, raits/configs/hmm_annual_vs_weekly_detection.txt

---
## Sub-task: Repo Cleanup (DONE 2026-07-01)
Status: DONE

### Completed
- [x] Full structural audit → AUDIT.md
- [x] Futures production verification (DEBT-2, HMM determinism, CWD sensitivity)
- [x] CLEANUP_PLAN.md — classification tables + execution plan
- [x] Bước 1: Annotated STALE (configs/final_params.yaml root), fixed __init__.py docstring, annotated 6 coexist/copy files
- [x] Bước 2: Archived 8 DEAD files → _archive/dead/
- [x] Bước 3: Archived 25 root SCRATCH files → _archive/scratch/root/
- [x] Bước 4: Archived 33 raits/+raits/raits/scripts/ SCRATCH files → _archive/scratch/raits/ + raits_scripts/
- [x] Bước 5: README markers added to 5 folders (orb_futures, tier2, xsect, nonequity, raits)
- [x] Final reconcile_gd0 PASS (MES 423t/$7,249 | MNQ 435t/$10,055 | MYM 438t/$7,466 | M2K 437t/$1,617)
- [x] Final reconcile_stress PASS (112 Stress days, 46 enter/match, 66 skip, 0 mismatches)

### CẦN XEM (user to decide — NOT touched)
- config_private.py — keep as-is (gitignored, contains Polygon API key)
- raits/raits/scripts/_check_oos_data.py — may be useful pre-OOS; user to decide archive or keep
- raits/raits/tests/decision/ — decision unit tests; keep (production test suite)

---

## Sub-task: Futures signal pipeline — live orchestration (IN PROGRESS)
Status: IN PROGRESS

### Completed
- [x] reconcile_nkd Phase 1 PASS — 496 NKD trades, 0 field mismatches, P&L diff $0.00
- [x] reconcile_nkd Phase 2 PASS — 496 trades, desired_position boundary checks OK → NKD safe to wire live
- [x] risk_sized fix in global_index/signal_layer.py — to_candidate now uses deploy_sim formula:
      risk_sized = n × mult × daily_ATR14.asof(entry_day) × point_value
      (was using chandelier stop-distance ATR → ~94.3% median discrepancy fixed to ~0%)
- [x] Unit tests updated for new to_candidate(daily_atr=, mult=) signature — all PASS
- [x] _asof_naive() helper: strips tz before asof() because daily_atr_series index is tz-naive
- [x] generate_today_signals: pre-computes atr_swing/atr_nkd; STRESS_MID uses atr_swing fallback
- [x] ROSKA4_MULT = NKD_MULT = 2.5 constants exported for test harness use
- [x] reconcile_gd0 baseline PASS (unchanged after signal_layer fix)
- [x] reconcile_stress baseline PASS (unchanged after signal_layer fix)
- [x] FuturesRunner + MockBroker orchestration VALIDATED vs deploy_sim:
      Net P&L $34,731.15 diff=$0.00 | taken swing=1226/stress=117/nkd=584 identical
      | rejected swing=507/stress=64/nkd=13 identical | OPEN=CLOSE=1927 residual=0
      | broker equity $84,731.15 == ACCOUNT+net

### Completed (HMM fit_C upgrade — 2026-07-02)
- [x] HMM sensitivity gate: fit_C (2024-12-31) passes flip check
      A→C label change 17.16% but economically justified (83/101 Normal→Stress in 2020+2022 bear)
      B→C label change 0.99% → HMM stable from here; annual re-freeze is safe
- [x] hmm_fit_end 2022→2024 in 4 production files:
      futures/basket.py (canonical), global_index/regime.py (NKD path),
      global_index/deploy_sim.py (CLI default), global_index/generate_replay_snapshots.py (REGIME indirection)
- [x] 5-layer reconcile with fit_C labels — all PASS (no runtime params passed):
      GĐ0: MES/MNQ/MYM/M2K MATCH | Stress: 4×instruments 0 mismatches (269 Stress days)
      NKD Phase 1: 515t/$12,306 field_mismatch=0
- [x] Baseline fit_C (paper): net $52,962 | Calmar 2.75 | MaxDD $2,789 → baseline_fit_c.txt
      Historical baseline (fit_A/conservative floor): net $47,838 | Calmar 2.38
      degradation.backtest_calmar = 2.3782 (fit_A floor, locked)
- [x] Snapshot regenerated fit_C: calmar=2.7456, per_cluster sum=net diff=0
- [x] Cleanup: backtest_combined.py + backtest_system.py annotated as harness (fit_A ref, not paper path)
- [x] regime.py docstring updated "2022-12-31" → "2024-12-31"

### Completed (NKD fit_C verification — 2026-07-02)
- [x] Verified NKD reads fit_C SPY labels (NOT fit_A residual) — direct measurement via nkd_fit_verify.py:
      225/1556 NKD session days (14.5%) receive different labels fit_A vs fit_C
      Trades differ: fit_A 496t/$11,177 vs fit_C 515t/$12,306 (+19 trades, +$1,129 IS-only)
      Flip breakdown: 189 Normal→Stress, 35 Calm→Normal, 1 Normal→Calm
      Confirmed: load_spy_regime() → RegimeLabels(lag=1) path uses hmm_fit_end="2024-12-31" ✅
      Snapshot NKD $13,694 = IS $12,306 + OOS 2023 tail ~$1,388 (no bug, different date range)

### Completed (verify_runner_real — 2026-07-02)
- [x] FuturesRunner + MockBroker + real signal_fn verified == deploy_sim fit_C:
      P&L diff=$0.00 | taken swing=1749/stress=312/nkd=645 identical
      | rejected swing=693/stress=117/nkd=46 identical | OPEN=CLOSE=2706 residual=0
      | broker equity $102,961.74 == ACCOUNT+net | ALL PASS
      Bug fixed: `desired_at` kept returning rejected trades as "desired" on every subsequent
      runner day (one spurious retry per day). Fix: only generate entry when new_ed==day_ts.
- [x] reconcile_gd0 no-harm PASS (MES/MNQ/MYM/M2K all MATCH after fix)
- [x] signal_layer unit tests no-harm PASS

### Completed (reconcile_swing_desired — 2026-07-03)
- [x] Swing desired_position() == backtest, all 4 instruments — PASS:
      Phase 1: MES 423t/$7,249 | MNQ 435t/$10,055 | MYM 438t/$7,466 | M2K 437t/$1,617 — MATCH
      Phase 2: 20/inst samples boundary-checked (entry_day + exit_day) — PASS
      Machinery identical to NKD (same backtest_swing_tf, return_open=True); only params differ.
      Safe to wire swing live.

### Completed (run_smoke_test — PASS 2026-07-08)
- [x] global_index/run_smoke_test.py — cold-start integration smoke test: ALL PASS
      P&L diff=$0.00 | taken swing=1799/stress=312/nkd=665 | rej 704/117/48 | OPEN=CLOSE=2776 residual=0
      broker_equity=$102,936.36 | circuit_breaker ref=run=0 | Calmar=2.74 MaxDD=$2,789
      No divergence from verify_runner_real.py — integration stack clean

### Completed (run_live_day.py — production entry point — 2026-07-08) ✓ LIVE VERIFIED
- [x] global_index/run_live_day.py: IBKRBroker → FuturesRunner → run_day(today)
      --dry-run LIVE VERIFIED 2026-07-08: connect → B3 reconcile → rollover check → fetch_bars → COMPLETE
      ~~Same data loading + signal_fn as run_smoke_test, but IBKRBroker (not MockBroker)~~
      ~~Full run: pre-computed backtest timelines; signal for today if parquet covers today~~
      NOTE: signal_fn REPLACED by Option C (see below)

### Completed (Option C — live runner fix — 2026-07-09)
- [x] AUDIT: 6 mismatches A-F confirmed. Root cause: timeline lookup copied from verify_runner_real.py.
      Impact measured: -$9,112 (-20.2%). See docs/futures/LIVE_RUNNER_AUDIT.md
- [x] Change 1 — runner.py:527: through=day → through=end-of-day (fixes Mismatch B)
      `_through = pd.Timestamp(day) + pd.Timedelta(hours=23, minutes=59)`
- [x] Change 2 — run_live_day.py: replace timeline signal_fn → generate_today_signals() wrapper
      Mismatches A+B fixed: `bars` param now USED (was `_bars` ignored); through=end-of-day
      Mismatch C fixed: generate_today_signals() calls desired_position() on concat(frozen+live)
      Mismatch D: requires cron change (5-min loop 14:05-15:55) — cron not yet updated
      Mismatch E (UT-2/UT-5): now ACTIVE (generate_today_signals is the live path)
      Mismatch F: runner.py docstring now matches implementation
      STRESS_MID: stress_bars_1015={} → DEFERRED Phase C2 (needs 10:20 ET morning cron)
- [x] Dead code removed: _desired_at(), _real_risk(), backtest pre-compute block, ledger, sorted lists
- [x] Offline tests: 31+14+42+68 = 155 tests ALL PASS after changes
- [x] Verify script written: global_index/verify_concat_desired.py (checklist a, PENDING run)

### Task: Stage 5ZB - operational audit: causal slot guard + runtime readiness
Status: DONE (2026-08-25)
Verdicts: READY_FOR_NEXT_TRACK1_SHADOW_WINDOW_OPERATIONALLY_AUDITED | PAPER_NOT_READY
No restart needed. No live/runtime file touched. No production file modified.

### Completed
- [x] Re-verified all five Stage 5ZA claims: 70 slots, per-slot causality, no end-of-window
      dependency, Calm grace bounded (allow 0-60s, refuse 61s+), strategy identity untouched.
- [x] **The 5ZA mutation pass that was left pending**: 24 mutations, ALL RED, each with a
      proven-green baseline. Covers every guard the stage prompt named.
- [x] `docs/futures/TRACK1_SHADOW_WINDOW_RUNBOOK.md` (NEW) - the post-window checklist, so the
      operator does not have to reconstruct it from stage reports. Pinned by two tests.
- [x] 32 tests in `scratch/test_track1_stage5zb_operational_audit_20260825.py`.
- [x] Deliverables: `scratch/track1_stage5zb_operational_audit_20260825.{md,json}`, Stage 5ZB
      section in the pipeline doc.

### Corrections this stage made
- **`TZ=America/New_York date` returns UTC in this shell.** Used it in 5X/5Y/5Z headers and for
  20 minutes here; it made a healthy scheduler look six hours hung. Three report headers
  corrected in place. Anchor with `zoneinfo`. The scheduler log stamps CALGARY time.
- **The next judgeable window is TODAY, not the 26th.** Earlier reports gave the NKD answer as
  the general answer. Calm 10:00 ET, Stress 10:35-12:30, Swing 14:05-15:55 all run today.
- Two mutations found weak TESTS, not weak code: the 70-slot fixture read the flag it was
  testing, and the ledger sweep accepted an empty result.

### Findings (all read-only)
- F1 `roska4_calm` opened a window 2026-08-24 that never closed - uncaught SpliceRefused
  (feed adds average/barcount). ALREADY FIXED elsewhere; 5ZB pins both halves from the file.
- F2 46 of 47 Ro 4 slots on 2026-08-24 refused `overlap_disagreement` at the 13:45 ET append
  boundary. Parquets repaired manually 7.5h AFTER those windows; the pre-flight now runs
  `--repair-boundary` automatically, first automatic run today 13:45 ET.
- F3 See the correction above.
- F4 `test_the_live_invariant_holds_on_the_real_files_right_now` (5Q4) fails until 13:45 ET
  daily. LEFT ALONE deliberately - another session's runtime invariant.

### Pending
- [ ] Inspect today's windows per the new runbook. First candidate: Calm 10:00 ET.
- [ ] `PAPER_SHADOW_EVIDENCE` 0 of 5 - blocked by EVIDENCE.
- [ ] `B1_broker_account_or_legacy_retirement` - blocked by OPERATOR DECISION.
- [ ] First-fill watch on the 11 Track 1 safety jobs - blocked by OPERATOR.
- [ ] F4's timing assumption is too strict; worth revisiting with whoever owns 5Q4.

### Files touched
docs/futures/TRACK1_SHADOW_WINDOW_RUNBOOK.md (new),
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md,
scratch/test_track1_stage5zb_operational_audit_20260825.py,
scratch/track1_stage5zb_mutations_20260825.py,
scratch/track1_stage5{x,y,z}_*.md (clock corrections), TASK.md

---

## Task: Stage 5ZC - post-window runtime check (first windows after 5ZB)
Status: DONE - PARTIAL by design (only 1 of today's 4 windows had closed and been exercised)
Checked 2026-08-25 ET 11:12-11:19. Read-only. Nothing restarted. No runtime evidence touched.

### Verdicts
- Next shadow window: **READY** - the route works (see the decided slots below).
- global_nkd 01:10-02:55  -> **FAIL** (22 slots, 0 decided, audited FAIL). PRE-FIX window;
  the 5V-1 causality fix landed between the 02:45 and 02:55 slots.
- roska4_calm 10:00       -> **NOT_ENOUGH_DATA** - the slot never ran.
- roska4_stress 10:35-12:30 -> OPEN at check time, not judgeable.
- roska4_swing 14:05-15:55  -> ahead.
- **PAPER_SHADOW_EVIDENCE: 0 of 5 qualifying days** (1 judgeable day on record, and it FAILED;
  no sleeve has ever PASSED). Measured via track1_paper_readiness.readiness().

### THE finding: the machine sleeps, and it is chronic
The Calm window did not run because **Windows slept for 13,020s (3h37m)**. The scheduler
process survived; its timer did not advance. Its own [HEARTBEAT] STALLED warning names the
cause and lists every missed job - including Calm 10:00, the Calm audit 10:10, and 7 Stress
slots.

Across all scheduler logs: **33 stall events, 16 days affected, 22.1 hours lost.** Today's was
the second worst on record.

**OPERATOR ACTION REQUIRED (not run by this stage):**
    powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0
    powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0
    powercfg /setactive SCHEME_CURRENT
The log names only the dc (battery) form; the ac form matters too. **No restart needed** - the
scheduler recovered on its own and runs current code.

### First decided slots on record
TRACK1_STRESS_1110 and _1115: decided=true, gate=true, freshness_allow=true, candidates=0.
Legitimate no-candidate case. **No overlap_disagreement** on either - first counter-evidence on
repaired history. Both wrote explanation records with a structural freshness proof and a data
sha256; absence of candidates is RECORDED, not merely absent.

### Also found
- Timing reconciles exactly: 24 coverage rows, 24 timing rows, no orphans. p50 2.5s / p95 18.7s
  / max 19.1s. None >= 300s.
- **Ledger asymmetry**: roska4_stress has slot rows and NO window_open (its first slot was eaten
  by the sleep), so it will close without ever opening. The runbook teaches only the inverse.
  CHECK AT 12:40 ET: does the audit refuse to call it judgeable?
- **Dashboard**: consistent, 0 incidents, no phantom overdue. One label collision - ops.py
  `freshness` is the IBKR connection (fresh); /api/v1/schedule-status `freshness` is the LEGACY
  runner's state snapshot (stale, 32.3h) because the legacy runner never writes during a shadow
  period. Classified as a READER mismatch, not a runtime failure. Left unchanged.

### Fixed: my own over-narrow test
`5V-1::test_the_live_ledger_rows_are_explained_and_untouched` pinned the DAY file at 22 rows
(Stage 5W) because the NKD WINDOW had closed. The file is one ledger per DAY shared by every
sleeve, and it broke when Stress wrote into it at 11:11 ET. Scoped to global_nkd; a second test
now pins the shared-file property.

### Still failing, classified, NOT touched
`5Q4::test_the_live_invariant_holds_on_the_real_files_right_now` - time-dependent, the pre-flight
runs at 13:45 ET and this was checked at 11:17. Re-check after 13:45.

### Remaining operational blockers
- [ ] **Machine sleep** - operator, powercfg. Blocks evidence accumulation more than anything else.
- [ ] PAPER_SHADOW_EVIDENCE 0 of 5 - blocked by EVIDENCE (and by the sleep above).
- [ ] B1_broker_account_or_legacy_retirement - blocked by OPERATOR DECISION.
- [ ] First-fill watch on the 11 Track 1 safety jobs - blocked by OPERATOR.

### Next checks (ET)
12:40 Stress audit (closed-without-open?) | 13:45 pre-flight, first auto --repair-boundary |
14:05-15:55 Swing | 16:20 spy_refresh_pm | 01:10 26th first NKD on the fixed gate

### Files touched
scratch/track1_stage5zc_post_window_runtime_check_20260825.{md,json},
scratch/test_track1_stage5v1_intraday_causality_20260825.py (over-narrow pin fixed),
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

---

## Task: Stage 5ZD - Track 1 signal diagnostics journal + job view integration
Status: DONE (2026-08-25). Signal diagnostics READY | Dashboard READY | Paper STILL BLOCKED.
NO RESTART NEEDED - the writer went live on save (slot subprocesses import fresh).

### Completed
- [x] `global_index/track1_signals.py` (NEW) - the diagnostics journal at
      `global_index/track1_runtime/signals/track1_signals_YYYYMMDD.jsonl`.
      Five statuses: SLOT_REFUSED / NO_SIGNAL / RAW_SIGNAL_FOUND / SIGNAL_REJECTED /
      SIGNAL_ACCEPTED_SHADOW. Strategy sleeves ONLY (refused at build time otherwise).
- [x] Wired into `observe_live_slot`, AFTER the coverage row and inside a guard, so a
      diagnostics failure can never cost a slot its evidence or change its decision.
- [x] Per-sleeve rule catalogue with thresholds READ FROM THE PARAMS (not restated).
- [x] Reader: `/api/v1/track1-runtime` -> compact `signals` summary. Absent file =
      "not yet observed", never an error. Disabled channel reports as disabled.
- [x] Job view: one compact line per Track 1 STRATEGY job; non-strategy jobs get NO key at all.
- [x] Dashboard: one panel row + one job line + expanded rule checks. No new card, no new
      column, wraps on mobile.
- [x] 68 tests (5 drive the REAL slot end to end), 30 mutations ALL RED,
      combined regression **720 passed** across 15 files incl. dashboard/DOM/contract.
- [x] Deliverables: `scratch/track1_stage5zd_signal_diagnostics_20260825.{md,json}`,
      Stage 5ZD section in the pipeline doc.

### LIVE PROOF
Production wrote 3 real rows before the stage finished, with no restart:
TRACK1_STRESS_1150 / _1155 / _1200 -> NO_SIGNAL, candidates 0, orders_enabled False.

### The honest gap this exposed (-> next stage)
Rule checks carry THREE sources: `measured` / `not_reached` / **`not_exposed_by_sleeve`**.
The sleeve detectors compute breadth, EMA and the gap internally and do NOT return them.
Observed in production: 6 measured, 24 not_exposed, 9 not_reached.

Re-implementing those rules in the diagnostics was REJECTED - a second copy of a strategy rule
disagrees with the one that trades. `not_exposed_by_sleeve` is never counted as a pass, and the
line says `blocker not reported (8 rules)` rather than falling silent.

- [ ] **NEXT: make the four sleeve detectors return their rule values.** Needs the artifact
      reproduction re-run behind it. Own stage.

### Tests corrected (both mine)
- `5Z::test_31` pinned exactly one `mode=` site; now asserts EVERY site is SHADOW_LIVE.
- `5Q3::test_this_suite_never_wrote_into_the_real_runtime_tree` asserted a production dir was
  empty - false since the live Stress slots wrote explanations at 11:10 ET. Now structural
  (relative dir constant + tmp root) plus a stray-file snapshot. A plain before/after snapshot
  would blame the suite for the live route's own writes.

### Unchanged
orders_possible=False; B1 + PAPER_SHADOW_EVIDENCE both blocking; no confirmation file;
env unset; no --allow-orders; no order journal; no Track 1 book.

### Files touched
global_index/track1_signals.py (new), global_index/run_live_day_track1.py,
monitor/backend/track1_runtime_reader.py, monitor/backend/job_journal_reader.py,
global_index/dash/realtime/realtime.js, global_index/dash/realtime/realtime.css,
scratch/test_track1_stage5zd_signal_diagnostics_20260825.py,
scratch/track1_stage5zd_mutations_20260825.py,
scratch/test_track1_stage5z_callsite_dryrun_20260825.py,
scratch/test_track1_stage5q3_live_frame_splice_20260824.py,
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

---

## Task: Stage 5ZE - job view operator diagnostics (health first, signal chip second)
Status: DONE (2026-08-25). NOTHING RESTARTED BY THIS STAGE.
Scheduler pid 48604 unchanged since 01:07 ET. Backend pid 35592 was restarted at 12:14 ET by
the operator (not by me), BETWEEN 5ZD and 5ZE.

### Part A audit - measured, not assumed
Before this stage the Track 1 job row showed: scheduler status (badge + Outcome) and duration.
It showed NOTHING about the runtime refusal reason, the 300s budget, whether the ledger row was
written, the per-job audit verdict, or checkpoint/book effects. The expanded "evidence list" is
ALWAYS EMPTY for a shadow slot - it is built from trade events, and a shadow slot emits none.

### Added
- [x] **Operational block** (expanded, above Signal): ran-at in ET + duration, budget verdict,
      ledger row written/missing, freshness pass/fail, live frame pass, per-job audit verdict,
      and "no checkpoint or book write expected in shadow". Falls back to the coverage LEDGER
      when a slot predates the signal journal (33 slots do).
- [x] **Signal chip** in the existing `.event-status` language, inside the job row on its own
      line. 7 labels, each with a REQUIRED plain-English tooltip via `.has-tip[data-tooltip]`.
      Non-strategy jobs get no chip.
- [x] **Operator language** replaced the developer block. Raw names, JSON thresholds and the
      UNKNOWN wall are GONE from the page - they ship under `signal.debug`, which NO code path
      in the page reads.
- [x] **Label mapper** with one owner in the backend. Unmapped names fall back to the raw name
      so a gap looks wrong on the page.
- [x] Track 1 panel reduced to COUNTS only.
- [x] REFUSED/MISSED/NO DIAGNOSTICS point at Operational rather than repeating the evidence.

### Tests
64 tests (11 in a REAL chromium), 26 mutations ALL RED, 5ZE+5ZD together 127 passed,
dashboard backend + realtime contract + realtime DOM + schedule-status + 5ZB = 327 passed.
`test_event_playback.py` not run.

### Mutations that found MY TESTS wrong
- M24: a 900px chip on a 380px screen stayed green TWICE. Both checks asked "does the PAGE
  overflow?"; the claim was "the chip does not widen its ROW". Now measured against the row.
- M12b: a browser check mutated in Python - the DOM fixture builds its own payload and never
  calls the patched function. Now mutated in the JS the browser loads.
  **Sixth consecutive stage with a source-patch-vs-behaviour mistake.**

### 6 Stage 5ZD tests updated
They pinned the UI this stage replaced (the row sentence, the rule grid, the per-sleeve panel
row, the pre-chip signal shape). Rewritten to assert the same intent, not deleted.

### OPERATOR ACTION (not run here)
The live dashboard serves the 5ZD shape and will not pick this up - `use_reloader=False`.
To make 5ZE live:
    python monitor\ops.py restart --no-scheduler --track1-only-shadow
Not run: the stage permits a backend restart only if needed for UI verification, and it was not
(verified in a real browser inside the test process). Also leaves today's Swing window at
14:05 ET undisturbed.

### Unchanged
orders_possible=False; B1 + PAPER_SHADOW_EVIDENCE blocking; no confirmation file; env unset;
no --allow-orders; no order journal; no Track 1 book; no strategy or scheduler code touched.

### Files touched
global_index/track1_signals.py, monitor/backend/job_journal_reader.py,
global_index/dash/realtime/realtime.js, global_index/dash/realtime/realtime.css,
scratch/test_track1_stage5ze_job_view_operator_20260825.py,
scratch/track1_stage5ze_mutations_20260825.py,
scratch/test_track1_stage5zd_signal_diagnostics_20260825.py,
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

---

## Task: Stage 5ZF - ops/report completeness audit before paper
Status: DONE (2026-08-25). READY for next shadow window | PAPER NOT_READY.
NOTHING RESTARTED. No runtime file touched. No strategy/scheduler/gate code changed.

NAMING: Stage 5ZE (job-view chip + operator diagnostics) is COMPLETE, not running.
This stage neither overwrote nor extended its UI.

### Audited (measured, not assumed)
- [x] **Job inventory**: 101 jobs, built by constructing the real scheduler in dry-run.
      70 strategy + 11 Track1 safety + 5 audit + 4 shared infra + 11 legacy drain.
      **0 unclassified. 0 legacy strategy jobs** (scheduler logs "45 not scheduled").
- [x] **SPY_REFRESH_PM**: emits normal job evidence (1 `_run` site), IS mirrored at 16:20,
      does NOT write preflight_state.json (AST-verified). No separate evidence system needed.
- [x] **Signal diagnostics placement**: matches the accepted contract exactly. rule_checks are
      STRICTER than asked - on the payload under `debug`, rendered by NO code path.
- [x] **Regime labels**: `spy_daily_live.csv` is a close series ONLY; labels are NEVER
      persisted, recomputed per read -> both SPY refreshes sufficient BY CONSTRUCTION.
      Monday reads Friday (verified). Holidays use `prev_trading_day`, same calendar.

### Fixed (two small reader fixes the audit proved necessary)
- [x] **SPY_REFRESH_PM was typed `other`** so a failure read "unclassified error". Now typed
      `spy_refresh_pm` with a real impact/action for failed AND missed ("check whether the
      machine was asleep" - 33 stalls is the observed mode).
- [x] **Stale runner label FIXED.** Root cause confirmed: `/api/v1/schedule-status` freshness
      reads the LEGACY runner snapshot, which nothing writes in track1-only (34.1h stale
      measured). Rail read "attention required" for the whole shadow period - an alarm that
      never turns off. Now: legacy staleness no longer decides route health; DEMOTED not
      hidden (`legacy_runner` block + `route_mode`); the rail answers from Track 1 evidence.
      Measured result: `stale` -> `late`, and `late` is TRUE (unexplained_overdue names
      TRACK1_CALM_1000 and TRACK1_STRESS_1035 - the slots the machine slept through).
      Legacy route behaviour unchanged, tested.

### CONFIRMED GAP: Track 1 Flex/PnL/report is MISSING, not partial
None of `session_report.py`, `flex_pull.py`, `paper_pnl_compare.py` knows Track 1 exists.
**Sharpest**: `run_maxhold_exit.py:171` and `run_stop_repair.py:180` hardcode
`trade_log_path=_CWD/'trade_log.jsonl'` with NO route scoping, while being handed
`--positions-path live_positions.track1.json`. The first Track 1 fill a safety job exits
writes a CLOSE row into the LEGACY trade log. One trade log on disk.

Six pieces missing before paper:
  1. Track 1 order journal -> PnL reader
  2. live_positions.track1.json -> open-position parity
  3. Track 1 fills -> Flex reconcile
  4. Track 1 safety exits -> route-scoped reporting  **DO FIRST - actively corrupts**
  5. route-aware session report / separate Track 1 report
  6. prevention of Track 1 rows folding into the legacy trade log (= #4)
Not implemented - own stage. 5 tests pin these as NEGATIVES so they fail if implemented.

### FINDING: regime label verification is warn-only
`verify_regime_labels` returns 0 on EVERY path - including "could not verify". A label drift
does not fail the job; the journal shows success. "Verified, no drift" and "could not check"
are the same number. **Acceptable for shadow, NOT for paper.** Should become a child failure.
Not changed here (behaviour change to a shared job; this stage was reader-level).

### Blockers by class
- evidence: PAPER_SHADOW_EVIDENCE 0/5 -> blocks paper
- operator: B1; machine sleep (33 stalls, 22.1h) -> sleep blocks the NEXT SHADOW WINDOW too
- code: the 6 reporting pieces; safety jobs writing the legacy log; warn-only label verify
- UI/ops: SPY_REFRESH_PM impact, stale runner label -> **both FIXED**

### Tests
33 new tests; regression **487 passed, 0 failed** across 8 files
(5ZF + schedule-status + dashboard backend + realtime contract + realtime DOM + 5ZE + 5ZD + 5ZB).

### Files touched
monitor/backend/job_journal_reader.py, monitor/backend/schedule_status.py,
global_index/dash/realtime/realtime.js,
scratch/test_track1_stage5zf_ops_report_completeness_20260825.py,
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

### NOTE: the dashboard fixes need a backend restart to go live
`use_reloader=False`. Same command as Stage 5ZE:
    python monitor\ops.py restart --no-scheduler --track1-only-shadow
Not run here.

---

## Task: Stage 5ZG - route-aware Track 1 safety exit reporting
Status: DONE (2026-08-25 ET 19:00-21:10). Blocker CLOSED in code+tests, NOT YET LIVE.
NOTHING RESTARTED. No runtime/live file written. No strategy, scheduler-behaviour, or gate change.

### Verdicts
- safety-exit legacy trade_log blocker : **CLOSED in code and under test** - see "not yet live"
- next shadow window                   : **READY**
- paper                                : **NOT_READY** (4 reasons, unchanged)
- scheduler/backend/runtime/live file  : **not touched**
- legacy safety behaviour              : **unchanged** (new OPTIONAL args only)
- Track 1 trade log path               : `global_index/track1_runtime/trade_log.track1.jsonl`
- route tagging                        : **implemented now**, `route="track1_candidate"`

### What was wrong (traced, not assumed)
`run_stop_repair.py:180` and `run_maxhold_exit.py:171` BOTH hardcoded
`trade_log_path=str(_CWD/'trade_log.jsonl')` and accepted no log/route argument, while the
scheduler handed their Track 1 copies `--positions-path live_positions.track1.json`.
Five per-route files existed (book, kill switch, lock, client id 90, maxhold marker); the
trade log was the missing sixth. `paper_evidence_reader` aggregates the whole trade log and
splits on NOTHING -> a Track 1 close would enter legacy's fill-quality and PnL gates.
Note: stop-repair IS a writer - B3 inside `FuturesRunner.__init__` books a matched stop and
writes a CLOSE row (that is why the hardcoded path was added 2026-08-17).

### Implemented
- [x] **`global_index/safety_trade_log.py`** (new) - one contract, both entry points:
      no arg = `trade_log.jsonl` byte-for-byte (NOT probed, NOT created);
      `--trade-log-path P` = P, proven writable NOW or exit 1;
      `--route R` = every row carries it; **`--route` alone is REFUSED**.
      Destination NEVER inferred from `--positions-path`.
- [x] **Probe runs BEFORE the positions check** - both scripts return early when the book is
      absent, which in shadow was every run; a check after it would never execute and a wrong
      path would surface at the first real fill. Append-open of the real file (what the writer
      does), not a directory permission bit. Creates it empty -> "never swept" vs "swept,
      closed nothing" become distinguishable.
- [x] **`TRACK1_TRADE_LOG_PATH`** in `track1_slots.py`; `PAPER_OUTPUT_POLICY['trade_log']` now
      names the real path + tag. Reader-collision checked: every Track 1 runtime reader globs a
      NAMED subdir; nothing enumerates the runtime root.
- [x] **Route tag**: `FuturesRunner(route=None)`, LAST in the signature; `_append_trade_raw`
      uses `setdefault`. Legacy rows gain NO key. Measured on the real log first: 28 rows,
      20 keys, `route` on none. Track1 keyset = legacy keyset + exactly {route}, both
      directions. OPEN rows tagged too. Value matches every other Track 1 artefact
      (`track1_candidate`), not the shorter `track1` the brief suggested.
- [x] **Scheduler**: both Track 1 safety bodies pass `--trade-log-path` + `--route` FROM THE
      CONSTANT. Job inventory unchanged: track1-only **101**, default 61, transitional 130.
      Legacy drain argv gains neither flag, in any mode.

### NOT YET LIVE - the distinction that matters
- entry-point changes ARE live (each safety job is a fresh subprocess importing current source)
- **the argv is NOT** - built inside the running scheduler, pid 48604, started 01:07 ET today
- => until a restart, Track 1 safety jobs are still invoked with no destination and no route
      and WOULD STILL WRITE THE LEGACY LOG. No restart performed (constraint).

### Observed today, NOT caused by this stage
`live_positions.track1.json` now EXISTS (mtime 13:56:19 Calgary, 0 positions, written by the
15:55 ET shadow slot). Both Track 1 safety jobs therefore stop taking their early return and
will acquire the lock and connect to IBKR on every sweep. New load, not a defect.

### Tests
- 40 tests, all 10 brief items + 6 more the code suggested (refusal must name the fallback;
  probe must not truncate; default must not be probed; check fires with no book; refusal must
  exit 1 not 0; `route` must be LAST in the signature).
- **Two-layer composition**: which destination the SCRIPT chooses (`main()` with broker class
  and FuturesRunner replaced) + what the RUNNER's REAL writer does with it
  (`FuturesRunner._append_trade` on an `object.__new__` instance so B3/B4 never run).
- **Mutations: 24/24 RED.** Source-level edits run in a SUBPROCESS - in-process patching
  cannot express scheduler wiring or statement ordering. Baseline proved green per mutation.
  Two harness defects found+fixed: restore compared file BYTES to re-encoded TEXT (always
  fails in a CRLF repo, aborted the sweep); two anchors that matched twice by indentation.

### Regression: 866 passed, 4 failed
5ZG 40 | dashboard backend + realtime contract + 5ZE + 5ZD + 5ZB + pre-sleep 392 |
17 FuturesRunner suites 222 | safety/scheduler suites 252 (+4 failed). No test_event_playback.

**5ZF test_17 was a deliberate tripwire ("if this becomes route-aware the report is stale")
and it FIRED within hours - inverted and kept. test_19 now asserts the part still missing.**

**The 4 failures are PRE-EXISTING, proven:**
- 3x assert `live_positions.track1.json` absent (5O, 5M-D, 5P): file mtime 13:56:19; the
  earliest file this stage edited has mtime 19:05:23 - five hours later.
- 5M-D `test_b1_still_blocks_orders` expects `[B1]`, gets `[B1, PAPER_SHADOW_EVIDENCE]`;
  that name lives in `track1_gates.py` / `track1_paper_executor.py` and appears **0 times**
  in all six files this stage touched.
- Pattern: absence standing in for "no test wrote it". 5P's OWN comment says so three lines
  above the assertion that still uses it; the mtime fix sits immediately below. NOT fixed
  here (unrelated; brief says do not chase).

### Paper blockers remaining
| blocker | class | open |
|---|---|---|
| PAPER_SHADOW_EVIDENCE 0/5 | evidence | yes |
| B1_broker_account_or_legacy_retirement | operator | yes |
| route-aware PnL / Flex / session report | code | yes - **5 of 6** pieces |
| verify_regime_labels warn-only | code | yes |
| Track 1 safety exits write legacy log | code | **CLOSED here** |

Measured: `orders_possible=False`, blocking `['B1...','PAPER_SHADOW_EVIDENCE']`, no
confirmation file, no orders dir, `TRACK1_ORDERS_APPROVED` unset.

### Files touched
NEW: global_index/safety_trade_log.py,
     scratch/test_track1_stage5zg_route_aware_safety_reporting_20260825.py,
     scratch/track1_stage5zg_mutations_20260825.py
MOD: global_index/track1_slots.py, global_index/runner.py, global_index/run_stop_repair.py,
     global_index/run_maxhold_exit.py, global_index/run_scheduler.py,
     scratch/test_track1_stage5zf_ops_report_completeness_20260825.py,
     docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

### NOTE: a scheduler restart is what makes this live
Not run here. The 5ZF dashboard fixes still need a backend restart too.

---

## Task: Stage 5ZH - quiet-window checkpoint audit
Status: DONE (2026-08-25 ET 21:10-22:00). Reader defect FIXED. Swing window now PASSES.
NOTHING RESTARTED. NO runtime evidence written or edited. No strategy / paper-gate change.

### Verdicts
- `checkpoint_wrong_route: route is None` : **LIVE DEFECT in the acceptance READER**
                                            (reproduced on demand; NOT stale, NOT expected)
- 2026-08-25 Swing window                 : **operationally valid**, and now **PASSES**
- future quiet complete Swing window      : **passes** (both artefacts present + dated today)
- runtime/live file touched               : **no** (all evidence still at 13:56-14:15 mtime)
- paper readiness                         : **unchanged**, NOT_READY

### Root cause (traced, not assumed)
`track1_shadow_acceptance` read `payload['route']` and `payload['cut_instant']` - **FLAT
schema-1 keys the schema-2 writer has NEVER produced**. In schema 2 the route sits under
`routes` and the day sits on each instrument entry as `last_day`. So `.get('route')` was
always None. **The check could never have passed**; before today the file did not exist, so
it failed on absence instead.

**Why nothing caught it**: 3 test suites build the fixture BY HAND as
`{"schema_version":2,"route":"track1_candidate","cut_instant":...,"sleeves":{}}`.
Measured: `route_checkpoint.load()` returns `{}` for it - **the route module REFUSES it**.
Nothing could produce or consume that payload. Fixture followed the reader, never the writer.

### Writer is CORRECT - the day proves the guard held
| sleeve | closed ET | complete | checkpoint |
|---|---|---|---|
| global_nkd | 02:55 | no (0/22) | no |
| roska4_stress | 12:30 | no (17/24) | no |
| **roska4_swing** | **15:55** | **yes (23/23)** | **yes, 15:56:19 ET** |
Empty instruments are a DESIGNED state ("present-but-empty says accounted for").

### SECOND instance of the same defect - the dashboard
`monitor/backend/track1_runtime_reader.py::_checkpoint` used the identical flat keys.
Panel showed `route: null, sleeves: []`. Fixed in the same stage.

### Contract chosen: OPTION C (already what the writer does)
`track1_bootstrap.write` produces BOTH artefacts in ONE call, atomically. Only the rule
had to learn it. New rule:
- absent -> `checkpoint_missing`
- unparseable / not schema 2 / no `routes` -> `checkpoint_unreadable`  **(new reason)**
- `routes` lacks `track1_candidate` -> `checkpoint_wrong_route`, naming what it DID hold
- entries present, all `last_day` == judged day -> **OK** (book not consulted)
- entries present, other day -> `checkpoint_wrong_day`
- no entries + book cut today -> **OK** (the quiet-window pass)
- no entries + book cut elsewhere -> `checkpoint_wrong_day`
- no entries + no/unreadable/undated book -> `checkpoint_day_unverifiable`  **(new reason)**
Also: reason classification moved OFF substring matching on the detail sentence, onto a
structured `code` + code->reason table.
UNCHANGED: checkpoint only demanded of a COMPLETE window; a passing checkpoint rescues nothing.

### Result
roska4_swing **PASS** - the FIRST Track 1 sleeve window ever to pass its audit.
Other three still FAIL on their own grounds (machine asleep for Calm + Stress 1035-1105;
NKD slots gate-refused as stale). None touched.
`all_slots_observed_no_action` survives as a reason ON a PASS - it never set the verdict.

### NAMED, NOT FIXED: the checkpoint cannot resume anything
The single production call site passes **no `frames`**, so `checkpoint_entries` skips every
instrument and the entry map is empty WHATEVER the day did. `get_entry` -> `{}` -> `usable`
refuses `no_entry` -> **every run replays in full**. Five instruments' identity never
recorded. Not fixed: loading 5 frames at close is real work inside a 78.5s p95 budget.
Harmless in shadow; NOT harmless once the route holds a position overnight. **Own stage.**

### Tests
46 tests; **every checkpoint produced by `route_checkpoint.save_route`, never by hand** -
plus an anti-recurrence guard that a hand-built payload must equal `empty_payload` exactly.
**Mutations: 15/15 RED.** One survivor on the first pass (the schema guard was shadowed by
the `routes` guard) - a real gap, now covered.

### Repaired neighbours (6 tests, 4 suites)
5Q build_green_day / naming-another-route / cut-on-another-day; 5Q1 + 5Q2 fixtures;
5P wrong-checkpoint (3 real ways to be wrong) + green-day reader (book present now).
Plus 2 absence-proxies fixed because this stage edited those files:
- 5P asserted `live_positions.track1.json` absent -> mtime check (live close writes it)
- 5Q2 asserted no real-tree file has today's date -> mtime (40 live files do)

### Regression: 836 passed, 0 failed
5ZH 46 | 5Q/5Q1/5Q2/5Q3/5P/route-checkpoint/bootstrap/dashboard-wiring |
5ZG/5ZF/5ZE/5ZD/5ZB/dashboard backend/realtime contract. No test_event_playback.
3 pre-existing failures in UNTOUCHED suites (stage3_route test_8c; 2x stage4b) - same
absence-proxy / later-gate classes, measured, left alone per brief.

### Paper blockers
PAPER_SHADOW_EVIDENCE (0 of 5; today is a FAIL day) | B1 | 5 of 6 reporting pieces |
verify_regime_labels warn-only | **NEW: checkpoint cannot resume**.
What moved: the "every sleeve PASSED at least once" clause now has 1 of its 4.

### Files touched
global_index/track1_shadow_acceptance.py, monitor/backend/track1_runtime_reader.py,
scratch/test_track1_stage5zh_quiet_checkpoint_audit_20260825.py (new),
scratch/track1_stage5zh_mutations_20260825.py (new),
scratch/test_track1_stage5q_post_window_audit_20260824.py,
scratch/test_track1_stage5q1_audit_semantics_20260824.py,
scratch/test_track1_stage5q2_explanation_integrity_20260824.py,
scratch/test_track1_stage5p_full_shadow_readiness_20260824.py,
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

### NOTE: backend restart needed for the dashboard half to go live
`use_reloader=False`. The 5ZF and 5ZG dashboard/scheduler changes are still waiting too.
    python monitor\ops.py restart --no-scheduler --track1-only-shadow
Not run here. The audit reader half IS live - `track1_audit` runs as a fresh subprocess.

---

## Task: Stage 5ZI - pre-paper error-proofing MAP (audit only)
Status: DONE (2026-08-25 ET 22:00-23:10). MAP ONLY - no code implemented.
NOTHING RESTARTED. No IBKR call. No runtime/live file touched. No strategy/gate change.

### Verdicts
- next shadow window : **READY** (only the machine sleeping stands in its way)
- paper              : **NOT_READY** - 6 machine gates open, 1 of them an operator decision
- top 3 stages       : **5ZJ** (make 5ZG live) -> **5ZK** (checkpoint frames) -> **5ZL** (regime tri-state)
- runtime file touched : **no**

### RANKED PRE-PAPER CHECKLIST
| # | item | shadow | paper | live | stage |
|---|---|---|---|---|---|
| 1 | machine sleep (16 missed jobs in one burst 08-25) | **YES** | yes | yes | **operator** |
| 2 | B1 account decision | no | **YES** | yes | **operator** |
| 3 | 5ZG argv not live (scheduler pid 48604 predates it) | no | **YES** | yes | **5ZJ** |
| 4 | checkpoint cannot resume (no frames at the callsite) | no | **YES** | yes | **5ZK** |
| 5 | regime verification warn-only + return DISCARDED | no | **YES** | yes | **5ZL** |
| 6 | order journal -> PnL reader | no | **YES** | yes | 5ZM |
| 7 | book -> open-position parity | no | **YES** | yes | 5ZM |
| 8 | Track 1 rows folding into legacy readers | no | **YES** | yes | 5ZM |
| 9 | planned stop NOT journalled (Order + OrderRecord have no stop field) | no | **YES** | yes | 5ZN |
| 10 | close_position / place_protective_stop unbuilt on the executor | no | **YES** | yes | 5ZN |
| 11 | executor unwired | no | **YES** | yes | 5ZN |
| 12 | evidence 0 clean days (2 of 5, both FAIL) | no | **YES** | yes | time + #1 |
| 13 | Flex reconcile | no | eval only | yes | 5ZM/later |
| 14 | route-aware session report | no | eval only | yes | 5ZM |
| 15 | broker working-stop reconcile | no | no | **YES** | 5ZO |
| 16 | orphan STP detection | no | no | **YES** | 5ZO |
| 17 | partial fill handling | no | no | **YES** | 5ZO |
| 18 | shared-account attribution | no | **unprovable** | yes | B1 |
| 19 | sleeve rule exposure (65% not_exposed_by_sleeve) | no | no | no | 5ZP |
| 20 | scheduler_processes drops the 3rd answer (NOT reachable) | no | no | no | hygiene |

### Key measurements this stage made
- **5ZG is not live, proven from the live log**: 18:20 argv has NO `--trade-log-path`, NO `--route`.
- **The book appearing changed safety-job behaviour**: sweeps 1 s -> **13 s** (they now
  connect to IB Gateway 13x/day on client id 90). Not a defect; new load since today.
- **Swing 08-25 re-evaluates to PASS**, but the RECORD says FAIL and the gate reads records.
  `every_sleeve_passed_at_least_once` -> `passed: []`. **This corrects the 5ZH claim.**
- **Order/OrderRecord have NO stop field** (measured field lists). The stop is placed by B4
  inside `FuturesRunner.__init__` via the safety sweep - no journal row anywhere.
- **Executor is missing 3 of 4 lifecycle verbs**: close_position, place_protective_stop,
  switch_same_symbol. `track1_switch` is imported by NOTHING and calls send_order twice.
- **verify_regime_labels**: 3 "could not verify" paths return 0 (== clean) AND the single
  call site `update_spy_csv.py:300` **discards the return value**. Drift is invisible end-to-end.
- **Signal rule exposure**: 32 rows, 324 checks - measured 64 (19.8%), not_reached 50 (15.4%),
  **not_exposed_by_sleeve 210 (64.8%)**, across 14 distinct rules.
- **Checkpoint budget**: swing p95 78.5 s / max 78.9 s vs the 300 s ceiling -> **221 s
  headroom**, and the checkpoint is written once at close. The frame RELOAD cost is
  **NOT MEASURED** - measure it first in 5ZK.
- **ops.py fail-open is NOT reachable**: both CLI paths check `scan.ok` and refuse before
  `start_scheduler`'s weaker inner guard. Latent trap for the next caller only.

### Operator actions pending
1. **Fix the sleep** - a power setting. Largest single cause of failed windows.
2. `python monitor\ops.py restart --no-scheduler --track1-only-shadow` (5ZE/5ZF/5ZH dashboard)
3. Scheduler restart for 5ZG's safety argv - higher risk, do it outside a window.
4. Optional: re-run the 08-25 sleeve audit so the corrected Swing verdict is on record.
   (Writes runtime evidence - operator's call. Would not make the DAY clean either way.)

### Stage plan
5ZJ make-5ZG-live | 5ZK checkpoint frames | 5ZL regime tri-state |
5ZM route-aware PnL/parity/report | 5ZN paper execution callsite + journal the stop |
5ZO stop lifecycle reconcile (NEEDS BROKER) | 5ZP sleeve rule exposure
**Dependency correction**: 5ZM reads a journal nothing writes yet -> have it consume the
5ZN DRY RUN's journal output rather than waiting for real orders.

### Cannot be finished in shadow - needs paper broker evidence
broker stop placement + reconcile | partial fills | SUBMITTED->outcome restart |
Flex statement reconcile | position attribution under a shared account

### Files touched
scratch/track1_stage5zi_prepaper_errorproofing_map_20260825.md (new),
scratch/track1_stage5zi_prepaper_errorproofing_map_20260825.json (new),
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md
(plus a correction to the 5ZH .md/.json gate claim - see "Key measurements")

---

## Task: Stage 5ZJ - make 5ZG live + verify Track 1 safety exit routing
Status: DONE (2026-08-26 ET 00:01-00:25). **5ZG IS LIVE - proven by a real sweep.**
RESTARTED (deliberately, per brief): scheduler AND backend. ONE runtime file created (empty).

### The nine answers
1. **scheduler restarted**: pid **48604 -> 18096** (old started 2026-08-24 23:07 Calgary,
   i.e. 14h before 5ZG was written)
2. **backend restarted**: pid **7872 -> 30604**
3. **5ZG live? YES** - the running scheduler launched a REAL sweep with both flags
4. **routed to trade_log.track1.jsonl?** destination PROVEN; **close row NOT proven** - the
   file is 0 bytes / 0 rows because the book holds zero positions
5. **legacy unchanged? YES** - same-second argv comparison; legacy log still 8486 B / 2026-08-15
6. **runtime data changed: EXACTLY ONE FILE** -
   `global_index/track1_runtime/trade_log.track1.jsonl` created 0 bytes by the writability probe
7. **orders still impossible? YES** - orders_possible=False, both blockers, no confirmation file
8. **remains before paper**: 6 items (below)
9. **next stage**: **5ZK checkpoint frames**

### PART A - pre-restart, measured
- live Track 1 safety argv had **NO `--trade-log-path`, NO `--route`** (20:20 line in the log)
- inventory from source: 101 (70 strategy / 11 safety / 5 audit / 4 infra / 11 drain / 0 legacy)
- backend was HALF-current: had 5ZF (`legacy_runner`, `route_mode`), lacked 5ZH
  (checkpoint summary read `route: null`) - it started 18:36, 5ZH was edited 19:44
- trade_log.track1.jsonl ABSENT; legacy log 8486 B / 2026-08-15; orders dir ABSENT

### PART B - restart
`python monitor\ops.py restart --scheduler --track1-only-shadow --yes`
- **`--yes` added**: this shell is non-interactive; without it `ensure_single` prompts and
  reads EOF. Documented purpose ("for unattended runs"), not a widening of the action.
- **Timing chosen, not taken**: ET 00:03, no window open, `runner scan ok=True pids=[]`,
  17 min to the next sweep, 67 min to the NKD window.
- **Second restart SKIPPED with evidence**: `restart --scheduler` restarts the backend too
  (transcript: "backend: stopped [7872] / backend=started pid 30604"). New backend started
  22:03:41, after every source edit. Verified live: 5ZH checkpoint summary now reads
  `route: track1_candidate` + `routes` + `entry_count`; 5ZF, 5ZD chip and 5ZE operational
  block all present. A second restart would replace a seconds-old process with an identical one.

### PART C - post-restart verification
- mode `track1-only-shadow`; `--shadow-resume` survived
- **inventory from the NEW process's own log**: 146 added - 45 removed = **101** (matches
  the source construction). Banner: 70 shadow slots / 11 safety / 5 audit / 45 legacy
  strategy not scheduled. spy_refresh_pm present. Legacy drain still scheduled.
- **argv (all 11 Track 1 safety jobs identical)**: `--positions-path live_positions.track1.json`
  `--trade-log-path global_index/track1_runtime/trade_log.track1.jsonl`
  `--route track1_candidate` `--client-id 90` `--lock-path runner.track1.pid`
- **legacy drain (all 11)**: `live_positions.json`, **no** `--trade-log-path`, **no** `--route`
- `--allow-orders` in NO fired argv, in any mode

### PART D - the first live sweep (00:20 ET), both routes in the SAME SECOND
```
22:20:00 [STOP_REPAIR_0020]        --positions-path live_positions.json --port 4002
22:20:00 [TRACK1_STOP_REPAIR_0020] --positions-path live_positions.track1.json
         --stop-path STOP_TRADING.track1 --lock-path runner.track1.pid --client-id 90
         --trade-log-path global_index/track1_runtime/trade_log.track1.jsonl
         --route track1_candidate --port 4002
22:20:11 [STOP_REPAIR_0020]        completed OK
22:20:13 [TRACK1_STOP_REPAIR_0020] completed OK
```
- `trade_log.track1.jsonl` created **22:20:01.18, 0 bytes, 0 rows** - **WRITABILITY PROBE ONLY**,
  recorded explicitly as briefed. Timing confirms the probe runs BEFORE the positions check
  and before the IBKR connect (launch :00 -> file :01.18 -> done :13).
- legacy `trade_log.jsonl` **untouched** (8486 B, 2026-08-15). No close row anywhere.
- both lock files released (`runner.track1.pid`, `runner.pid` absent) - the atexit release
  worked on a path that connects to the broker.
- **RUNTIME CLOSE-ROW PROOF IS PENDING** until the route holds a position. The empty file is
  proof of a destination, NOT of a delivery.

### PART E - tests
**0 new tests** - all five brief items were already pinned (5ZG argv x2, 5ZF/dashboard,
5ZH checkpoint, 5M-D + 5O for `--allow-orders`). **Regression 433 passed.**
One repair inside this stage's surface: `5O::test_no_switch_or_state_file_was_created`
asserted `live_positions.track1.json` absent; the live 15:55 close writes it by design ->
moved onto the mtime check two lines below (identical to the 5P repair). 26 passed.
Left alone: the two 5M-D failures (gate-list staleness, already classified in 5ZI).

### Files changed on disk
RUNTIME: `global_index/track1_runtime/trade_log.track1.jsonl` (created, 0 B, probe) - ONLY ONE
SOURCE: `scratch/test_track1_stage5o_route_aware_safety_20260824.py` (one assertion moved)
UNCHANGED (mtime-verified): checkpoint, both books, both maxhold markers, audits, signals,
window coverage, legacy trade_log. **No audit record rewritten. No book/checkpoint edited.**

### REMAINING BEFORE PAPER (6, one fewer than 5ZI)
| # | item | class |
|---|---|---|
| 1 | machine sleep (16 missed jobs in one burst on the 25th) | **operator** |
| 2 | B1 - separate account or proven-flat legacy book | **operator decision** |
| 3 | checkpoint cannot resume (callsite passes no frames) | **5ZK** |
| 4 | regime verification warn-only + return discarded | **5ZL** |
| 5 | route-aware PnL / parity / legacy-reader split | **5ZM** |
| 6 | planned stop not journalled; close_position + place_protective_stop unbuilt | **5ZN** |

**REMOVED from the list: "5ZG's argv is not live".** Evidence gate unchanged: 2 judgeable
days, both FAIL, 5 required - which is item 1's consequence more than anything else's.

### Next: 5ZK
It is the only remaining item with a MEASUREMENT GATE in front of it (can the closing slot
reuse frames, or must it reload? unmeasured - and if the cost is large the stage changes
shape). Cheap, one callsite, no broker. 5ZL is a close second. **Not 5ZM next**: a PnL reader
over the order journal would read a journal nothing writes yet.

### NOT claimed by this stage
paper readiness | broker-flat | orphan-STP safety | that a real Track 1 close was routed

### Files touched
scratch/track1_stage5zj_make_5zg_live_20260826.md + .json (new),
scratch/test_track1_stage5o_route_aware_safety_20260824.py,
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

---

## Task: Stage 5ZK - checkpoint frames and resume correctness
Status: DONE (2026-08-26 ET 00:28-01:05). **The checkpoint can now resume: 0 -> 5 entries,
5/5 Resumed.** NOTHING RESTARTED (and none needed). NO runtime file written or edited.

### The ten answers
1. runtime checkpoint/book/audit changed? **NO** - both still 2026-08-25 13:56:19 (Part A baseline)
2. live checkpoint still quiet/empty and VALID? **yes** - book proves route, day, zero positions
3. entries usable when the book has open positions? **YES** - 5/5 `Resumed`; a position
   survives the round trip. *Caveat*: that path is built+tested but NOT REACHABLE yet (see below)
4. frames reused or reloaded? **RELOADED** - and the "reuse is impossible" claim was WRONG (below)
5. cost/headroom? **6.0-6.2s** whole write; **221s headroom**; closing slot 78.5s -> ~84.7s (~2%)
6. fails closed on open book with no entries? **YES** `checkpoint_entries_missing_for_open_book`
   (+ mirror `checkpoint_book_disagrees_with_entries`)
7. strategy/backtest identity unchanged? **YES** - hashes identical both directions; writer
   imports no signal/rule/gate module (AST-checked)
8. orders still impossible? **YES**
9. next shadow window READY? **YES** - NKD opened 01:10 ET, 4 min after this was written
10. next stage? **5ZL regime tri-state**

### THE MEASUREMENT THAT DECIDED THE DESIGN
The daily append runs **13:45 ET**. At a 15:55 close the parquet holds TODAY only to 13:44
while YESTERDAY runs to 23:59 - so the next append **backfills today's afternoon**, which sits
BELOW the cut a fingerprint through today would use.
```
fingerprint through NEWEST stored day, after the next append : CHANGED
fingerprint through PREVIOUS day,      after the next append : unchanged   (MES and MNKD)
```
=> an entry naming the cut day is refused by every later resume with `fingerprint_rowcount`.
**A correct entry names the LAST COMPLETE day**, derived from the frame's own day index.

### A CLAIM OF MINE THE DATA CORRECTED
I wrote (code + test) that the slot's in-memory JOINED frames were the wrong ones because
splicing changes the hash. **The test written to prove it went GREEN.** True through the CUT
day; FALSE through the last complete day, where the appended bars sit above the cut and both
frames hash identically. **Reuse WOULD have worked.** Reload is a CHOICE:
- the parquet is what the resume path reads -> fingerprinting it IS the contract
- the closing slot holds only its own sleeve's instruments (4 at Swing, 1 at NKD, never 5)
- 6s vs 221s headroom buys the simpler seam
Pinned by a test that goes red the day the join rewrites history below the cut.

### Implemented
- `last_complete_day(df)`; `checkpoint_frames(data_paths)` (reports failures by name, never raises)
- `write_route_checkpoint`: **`frames=None` = LOAD THEM; `frames={}` = deliberately none.**
  They used to mean the same thing - exactly how production wrote an empty checkpoint every window.
  Return now carries entry_count / instruments / last_day_by_inst / frames_unavailable.
- `checkpoint_entries(..., last_day_by_inst=None)` - omitted = byte-identical (asserted)
- acceptance: **the book is the day proof in BOTH cases**; open-book guard both directions;
  new codes `entries_missing_for_open_book` / `book_disagrees_with_entries` / `history_stale`;
  `CHECKPOINT_MAX_HISTORY_LAG_DAYS = 5` (named judgement call)

### 5ZH's entry-day rule REPLACED
Old: entries must be dated the judged day, book not consulted. The measurement disproves it -
a correct entry names the PREVIOUS day - so the rule would have failed every real checkpoint.
New: book proves the day always; entries asked only "not from the future, not stale".
6 tests in the 5ZH suite rewritten. **Live evidence re-judged: nothing moved** (quiet checkpoint
still OK, roska4_swing 2026-08-25 still PASS, other three still fail on their own grounds).

### NOT FIXED HERE: the route has NO CROSS-DAY BOOK
`observe_live_slot` builds a fresh `Track1Book` per slot and never loads the persisted one;
`write_route_checkpoint` synthesises `positions: []` when handed no `book_state`. Today's book
is a correctly-shaped "nothing is held" marker, accurate only because nothing is held.
=> **the open-position path is built and tested but NOT REACHABLE in production.** That is
position lifecycle = **5ZN**. The fail-closed guard stands in the gap until then.

### Tests
38 tests, REAL parquets (a synthetic frame would make every budget claim meaningless; the
budget test asserts >1M rows per frame so it cannot pass on a toy). All 9 brief items covered.

### Regression: 572 passed, 1 skipped, 2 failed
Repaired IN SURFACE: 6 absence-proxies in the three suites that exercise
`write_route_checkpoint` (mtime instead of absence) - **sixth occurrence of that pattern**.
Left (pre-existing, not this surface): 5D job count 61 vs 60; 5E blocker set gained
PAPER_SHADOW_EVIDENCE.
**Newly surfaced, pre-existing, NOT fixed**: `5m1::test_every_engine_params_built_in_production_
states_its_fill_law` fails on `track1_signals.py:224` (`NormalR4Params()` with no fill law).
Stage 5ZD's file, mtime 12h older than any edit here. Diagnostics-only - reads thresholds to
print them, decides nothing - but if the default drifted the journal would print a number the
decision never used. Belongs with **5ZP** rule exposure.

### Part E - liveness: NO RESTART NEEDED
Every changed module is imported by a SUBPROCESS (scheduler spawns
`python -m global_index.run_live_day_track1` for slots, `_run(argv)` for audits). Dashboard
reader untouched -> backend unaffected. Restarting 10 min before a window for no gain would
have been the wrong trade.

### REMAINING BEFORE PAPER (5, one fewer)
| # | item | class |
|---|---|---|
| 1 | machine sleep | **operator** |
| 2 | B1 account decision | **operator** |
| 3 | regime verification warn-only + return discarded | **5ZL** |
| 4 | route-aware PnL / parity / legacy-reader split | **5ZM** |
| 5 | planned stop not journalled; close_position + place_protective_stop unbuilt; **no cross-day book** | **5ZN** |

**REMOVED: "the checkpoint cannot resume anything."**

### Files touched
global_index/run_live_day_track1.py, global_index/track1_bootstrap.py,
global_index/track1_shadow_acceptance.py,
scratch/test_track1_stage5zk_checkpoint_frames_resume_20260826.py (new),
scratch/test_track1_stage5zh_... (section C rewritten),
scratch/test_track1_stage5d/5e/5f_... (6 absence proxies -> mtime),
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

### NOT claimed
paper readiness | open-position path reachable in production | broker-flat | orphan-STP safety
| that reusing the in-memory frames would have been impossible

---

## Task: Stage 5ZL - regime verification tri-state, fail closed, visible end to end
Status: DONE (2026-08-26 ET 01:30-02:15). PASS/DRIFT/UNKNOWN live. NOTHING RESTARTED.

### !!! INCIDENT - A TEST OF MINE OVERWROTE `global_index/preflight_state.json` !!!
**When**: 2026-08-25 23:42:02 Calgary. **Caught by**: this suite's own "no production file was
written" test - the only reason it was noticed.
**Cause**: the first test helper fired the pre-flight job body with the SUBPROCESS RUNNER
replaced but not the STATE PATH. Replacing the launcher does not make a job body safe when the
persistence happens in the PARENT.
**Before**: 7 days (08-17,18,19,20,21,24,25 all true). **After**: `{"2026-08-26": true}` -
a FABRICATED CLEARANCE for a day whose pre-flight has not run (it fires 13:45 ET).
**Blast radius**: the running scheduler (pid 18096) holds the true 7 days in memory and reads
the file only at startup -> unaffected; its 13:45 save rewrites it correctly.
**THE FILE SELF-HEALS IN ~12 HOURS.** Exposure = a scheduler restart before then.
**FIXED**: the helper now redirects every state path to tmp_path; incident recorded in the
test's own docstring.
**RESTORE ATTEMPT WAS BLOCKED** (correctly - live state, standing constraint). Not worked
around. Reconstructed from the scheduler logs (mtime = that day's PRE-FLIGHT OK instant;
`_PREFLIGHT_KEEP = 7`; every pre-flight OK, no FAILED line; matches "restored 7 day(s)"):
```
python -c "import json,os; from pathlib import Path; p=Path('global_index/preflight_state.json'); d={k:True for k in ['2026-08-17','2026-08-18','2026-08-19','2026-08-20','2026-08-21','2026-08-24','2026-08-25']}; t=p.with_suffix('.tmp'); open(t,'w',encoding='utf-8').write(json.dumps(d,indent=2)); os.replace(t,p); print(p.read_text(encoding='utf-8'))"
```
2026-08-26 deliberately absent. **Doing nothing is also defensible** if no restart happens
before 13:45 ET.

### The eleven answers
1. statuses: **PASS / DRIFT / UNKNOWN**, 10 codes, each in exactly one status
2. old collapses: **FIVE**, not four - all now UNKNOWN (below)
3. DRIFT blocks readiness? **YES**   4. UNKNOWN blocks readiness? **YES** (incl. no record)
5. reaches exit code? **YES for the 16:20 post-close refresh**; deliberately NOT the 13:45 preflight
6. post-close failure visible on its own? **YES**, and it does not write preflight_state (AST)
7. freshness semantics changed? **NO** - module untouched, does not import regime_verify (both asserted)
8. runtime file changed? **ONE**, by a test of mine (above). Everything else at baseline.
9. orders impossible? **YES**   10. next shadow window READY? **YES** (tonight's NKD ran untouched)
11. remaining: 4; **next = 5ZM**

### THE FIVE COLLAPSES (all returned 0 == clean)
| path | now |
|---|---|
| `futures._validated_core` unimportable | UNKNOWN / engine_unavailable |
| either CSV fails to load | UNKNOWN / inputs_unreadable |
| `label_regimes` raises | UNKNOWN / labelling_failed |
| **no overlapping dates** (logged "HMM stable"!) | UNKNOWN / no_overlapping_dates |
| no snapshot (**5th, found here**) | UNKNOWN / no_snapshot |
And the result went NOWHERE: call site discarded it; `__main__` called `main()` bare so the
return never reached the exit code; scheduler keeps only ERROR from an exit-0 child; the drift
line was a WARNING. **Invisible end to end.**

### Implemented
- **`global_index/regime_verify.py`** (new, route-neutral - legacy's preflight runs the same
  check): `VerifyResult`, 10 codes, constructor REFUSES a code from another status, dated
  append-only record at `global_index/regime_verify/`, `latest()` = UNKNOWN for no record /
  unreadable / foreign status / >7 days old. **The module decides nothing.**
- `update_spy_csv`: returns `UpdateOutcome` (== int still works for old callers); both early
  returns carry UNKNOWN; `--verify-strict`, `--verify-root`; **`sys.exit(main())`**.
- scheduler: 16:20 runs `--verify-strict` with **three distinct failure messages**;
  13:45 documented as deliberately NOT strict; success line now verifies its claim.
- **NEW GATE `REGIME_LABEL_VERIFICATION`** - measured, released only by PASS, no confirmation
  can wave it through, fails closed. blocking_now is now **3**.
- dashboard `regime_verify` block, three distinct readings, never collapsed to ok/stale.

### SECOND LIVE FINDING (same defect, one job over)
16:20 job logged "OK - the daily series now covers 2026-08-25"; **the series ends 2026-08-24**
(measured, mtime 14:20:01 = that very run). It printed the sentence on any exit-0 having
checked nothing - Polygon's SPY daily bar is not final at 16:20 ET. **Fixed**: reads the series'
last date, or says the close was not available yet. No harm: last night's 9 NKD slots all
decided, none refused on freshness.

### Tests: 48. Regression 523 passed, 0 failed.
Engine STUBBED for PASS/DRIFT so the outcome is chosen, not hoped for. CLI cases run in a
SUBPROCESS (an exit code cannot be asserted in-process). Structural checks by AST.
- **2 x 5ZF tripwires FIRED and were inverted** (test_26 carried "if this now raises the
  finding is closed"; test_27 said a drift is not visible as a job failure)
- 2 x 5S gate tests updated (a control satisfying only the gates that existed the day it was
  written stops being a control)
- 1 x 5ZK runtime scan narrowed (it asked whether ANYTHING under the runtime root was written
  during the run; the live NKD window was open and writing)
- 3 x 5Z freshness failures **NOT from this stage** (freshness untouched, mtime 2026-08-24
  10:24, and a passing test asserts it does not import regime_verify). **Cause not
  established** - recorded rather than waved at.

### Liveness (nothing restarted - the NKD window was open)
LIVE NOW: the verification + strict exit (both SPY jobs are subprocesses). Today's 13:45
pre-flight will be the first to record a status.
**NOT live until a SCHEDULER restart**: `--verify-strict` and the corrected success line (they
live in pid 18096's job bodies).
**NOT live until a BACKEND restart**: the dashboard `regime_verify` block.

### REMAINING BEFORE PAPER (4)
| # | item | class |
|---|---|---|
| 1 | machine sleep | **operator** |
| 2 | B1 account decision | **operator** |
| 3 | route-aware PnL / parity / legacy-reader split | **5ZM** |
| 4 | planned stop not journalled; close_position + place_protective_stop unbuilt; no cross-day book | **5ZN** |
Plus the new gate, which is not work: it opens the first time the 16:20 job records a PASS.
**REMOVED: "regime verification is warn-only and its return is discarded."**
5ZI's dependency correction still stands: have 5ZM read the DRY RUN's journal output.

### Files touched
NEW: global_index/regime_verify.py, scratch/test_track1_stage5zl_regime_tristate_20260826.py
MOD: global_index/update_spy_csv.py, global_index/run_scheduler.py,
     global_index/track1_gates.py, monitor/backend/track1_runtime_reader.py,
     scratch/test_track1_stage5zf_..., scratch/test_track1_stage5s_...,
     scratch/test_track1_stage5zk_..., docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

---

## Task: Stage 5ZM - route-aware reporting, PnL, Flex surface, legacy-reader split
Status: DONE (2026-08-26 ET 02:20-03:05). NOTHING RESTARTED. NO runtime file changed.
Operator's preflight restoration VERIFIED (7 days, 2026-08-26 absent) and now PINNED BY A TEST.

### The eleven answers
1. readers: **9 reporting readers in 5 classes** (below)
2. made Track1-aware: new `global_index/track1_report.py` + route split in 2 legacy aggregates
3. Track1 ever falls back to legacy? **NO** - asserted 3 ways, one by WATCHING EVERY FILE IT OPENS
4. legacy reports unchanged? **output yes**; both aggregates now EXCLUDE foreign rows + SAY HOW MANY
5. dry-run feeds expected reporting? **YES**, every such row labelled INTENDED
6. broker/Flex PnL verified? **NO** - 2 reasons, both measured
7. parity: **PASS (both_flat)** + `attribution_unknown` in the same payload
8. runtime file changed? **NO**   9. orders impossible? **YES** (3 blockers)
10. next shadow window READY? **YES**   11. next = **5ZN**

### Reader classification (AST over literals; 34 files mention the 4 artefact families, 9 report)
| class | modules |
|---|---|
| 1 legacy-only by design | reconcile_statement, entry_time_reader, execution_quality_reader, runner_positions_reader, report_reader |
| 2 already Track1-aware | track1_runtime_reader |
| 3 **shared, split required** | **paper_evidence_reader, paper_pnl_compare** |
| 4 missing Track1 impl | session_report (**stays missing, deliberately**) |
| 5 **cannot verify until broker evidence** | flex_pull |

### Built
- **`global_index/track1_report.py`**: three artefact states **not_produced / empty /
  available** (a missing book reports `positions: None`, NOT 0). Every row must carry
  `route=track1_candidate` or it is INVALID and counted separately. Reads NO legacy path -
  asserted by AST, by **wrapping `open`/`Path.read_text` and recording every path touched**,
  and in its own payload.
- **legacy split** in `paper_evidence_reader` (`_trade_records_split`) and **`paper_pnl_compare`
  at BOTH row loops**. Excluded rows are RETURNED and REPORTED
  (`trade_log_foreign_route_rows`, `trade_log_foreign_routes`). Zero is expected; non-zero
  means a Track1 row reached legacy's file.
  **DESIGN POINT**: the filter excludes FOREIGN routes, it does not SELECT legacy ones. Every
  pre-5ZG row is untagged, so "keep only legacy-tagged" would have silently emptied both
  reports of their whole history - and looked like a working filter. Pinned.
- dashboard `reporting` block, `paper_ready: false`, fails closed.

### BROKER EVIDENCE: false, two separate reasons
`no_track1_orders_have_been_placed` (closes itself on first fill) AND **`route_unattributed`**.
**Measured**: the newest Flex statement has **37 fields**, NONE of them route/strategy/
orderRef/clientId - only `ClientAccountID`, one account. So even after fills exist a statement
**cannot say which route made them** while one login serves both. Pinned by a test against the
real file. **A second, sharper reason B1 must close BEFORE paper.**

### PARITY: PASS (both_flat) + attribution_unknown
5 outcomes; **UNKNOWN is never PASS**. book missing -> UNKNOWN | both flat -> PASS (with the
caveat in the same payload) | book flat + journal rows -> FAIL | book positions + no journal ->
FAIL "a position nobody can account for" | both populated -> UNKNOWN (needs real fills).

### Tests: 41. Regression **570 passed, 0 failed** (5ZM/5ZL/5ZF/5ZG/5S/5ZK + all of monitor/).
Notable: the file-watching test - "no legacy literal" is TEXTUAL; running the reader with
`open`/`read_text` wrapped is BEHAVIOURAL and survives a path built by concatenation.
**5ZF test_15 tripwire FIRED and was SPLIT**: 2 modules still route-blind stay pinned;
paper_pnl_compare came off because it now NAMES track1_candidate (to exclude it) though it
still reads only legacy paths. A new test draws exactly that distinction.

### NOT built, and why (stated rather than quietly skipped)
- **route-aware SESSION REPORT**: session_report.py is a legacy-book report; a Track 1 section
  before Track 1 has anything to report is a page that says nothing. **Still classified missing.**
- **FLEX RECONCILE**: *cannot* be built, not merely was not - see the 37-field measurement.

### REMAINING BEFORE PAPER (3)
| # | item | class |
|---|---|---|
| 1 | machine sleep | **operator** |
| 2 | B1 (now with a second, sharper reason) | **operator** |
| 3 | planned stop not journalled; close_position + place_protective_stop unbuilt; **no cross-day book** | **5ZN** |
Plus 2 machine gates that open by themselves: PAPER_SHADOW_EVIDENCE (clean days) and
REGIME_LABEL_VERIFICATION (first 16:20 PASS).
**REMOVED: "route-aware PnL / parity / legacy-reader split"** (with the two qualifications above).

### Liveness
The Track 1 reader is importable now. **The running backend still serves the OLD reader** - the
`reporting` block appears after a backend restart, which was not performed (NKD window open).

### Files touched
NEW: global_index/track1_report.py, scratch/test_track1_stage5zm_route_aware_reporting_20260826.py
MOD: monitor/backend/paper_evidence_reader.py, monitor/paper_pnl_compare.py,
     monitor/backend/track1_runtime_reader.py, scratch/test_track1_stage5zf_...,
     docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

---

## Task: Stage 5ZN - planned stop, executor lifecycle, cross-day book
Status: DONE (2026-08-26 ET 03:20-04:20). NOTHING RESTARTED. NO runtime file changed.
No IBKRBroker constructed. No production order journal written. Orders still impossible.

### The eleven answers
1. runtime/live file changed? **NO**
2. orders impossible? **YES** (3 blockers, no confirmation, no orders dir, no ib_insync import)
3. planned stop lives on: **`PlannedStop`** + `OrderRecord` + `JournalRecord` (NOT on
   `broker.Order`/`Fill` - those are shared with legacy and gained nothing)
4. sendable without a plan? **NO** - refused in two places before anything could send
5. close/stop/switch: **BUILT, intent-only** (they journal + refuse; the send step is NOT built)
6. cross-day book safe? **YES NOW** - it was not before
7. unverified until paper: **one thing** - that a broker actually holds the planned stop
8. legacy unchanged? **YES**   9. strategy identity unchanged? **YES**
10. next shadow window READY? **YES**
11. only evidence/operator/paper left? **YES for Track 1's own code** - one caveat below

### LIVE CONFIRMATION OF 5ZK (the 02:55 ET NKD close, between stages)
Checkpoint entries **0 -> 5** (swing 4, nkd 1). `global_nkd 2026-08-26` -> **PASS**.
"route ok, 5 entr(y/ies) through ['2026-08-24'] (2 days behind), book cut 2026-08-26,
0 open position(s) matched". **Second window ever to pass; first with a resumable checkpoint.**

### What was missing (measured)
`Candidate` HAS `stop_price` and it survives admission. `candidate_to_order` builds an `Order`
with nowhere to put it; `OrderRecord` had nowhere either. So the plan was dropped at the edge
of the order path, and the protective stop was placed later by the safety sweep in ANOTHER
PROCESS - nothing anywhere held both the intended price and the placed one.

### Built
- **`global_index/track1_planned_stop.py`**: `PlannedStop` (13 fields), 4 refusal codes,
  `assert_sendable`. **The price is COPIED, never recomputed** - a test asserts by AST that the
  only arithmetic in `from_candidate` is the two subtractions making `stop_distance`.
  Refuses: no price / not a number / NaN / zero-or-absent qty / **stop on the wrong side of
  entry** (that is a target, not a stop - it would trigger at once).
- `plan_entry(candidate,...)` -> `(Order, PlannedStop)`; `candidate_to_order` untouched.
- stop fields **appended LAST + defaulted** on `OrderRecord` and `JournalRecord` (+ `qty`);
  old positional callers still construct; old rows still read back. Both asserted.
- **three intent-only verbs**: `close_position`, `place_protective_stop`, `switch_same_symbol`.
  Every refusal precedes the journal row. The switch journals **TWO legs, close first** (a
  switch that opened before it closed would double exposure for the gap).
  AST-proven: none of them mentions `self.broker`.
- **book carried across days**: no book -> flat one created; book exists -> carried + restamped;
  **unreadable -> the write is REFUSED and the file left alone**. Another route's book refused.
  Intending a close does not move the book.

### DEFECT FOUND BY BUILDING ON IT
`track1_paper_executor.BOOK_PATH` was `global_index/live_positions.track1.json` - **a path the
book has never occupied**. `read_book` calls a missing file empty, so that constant made
`reconcile_at_startup` compare an ALWAYS-empty book against the broker and conclude the route
was flat whatever it held. Never fired (nothing imports the executor). **Fixed, and now read
from `track1_slots`.** A 5X test was green BECAUSE of it (asserting the book absent, true only
of a file nobody writes) - rewritten to what it meant.

### A PIN I NEARLY WEAKENED AND DID NOT
6 tests across 5 suites assert **nothing which runs imports the order path** - half the
argument that there is no route from scheduler to broker. My first reporting block imported the
executor for a panel field and broke all six. **Rejected**: loosening the pins. **Done**: the
report DECLARES the verb names, and a test compares that against the real class where imports
are free. Production's import graph unchanged.
Also widened, with its reason: 5V's "every serialised value is str|int|float" now admits
`None`, because `None` = "no plan travelled with this row" and `0.0` would collide with a real
stop. `None` round-trips through JSON unchanged.

### Tests: 52. Regression **690 passed, 0 failed**
(5ZN/5ZM/5ZL/5ZF/5ZG/5ZK/5ZH/5S/5O + the whole 5T-5Z order-path family + all of monitor/ +
legacy stop and max-hold suites). The fake broker RAISES on send_order and place_stop.

### REMAINING BEFORE PAPER (5) - none is a design question
| # | item | class |
|---|---|---|
| 1 | machine sleep | **operator** |
| 2 | B1 - separate account or proven-flat legacy book | **operator** |
| 3 | five clean judgeable days | time, once 1 is fixed |
| 4 | the regime gate's first PASS | time - the 16:20 job records it |
| 5 | broker stop proof, partial fills, order in flight across a restart | **paper only** |

**CAVEAT stated rather than buried**: the lifecycle verbs produce INTENT; **the send step is
deliberately not built**. Wiring a real call site is a stage of its own and should come AFTER
the gates open - the day it is built is the day the distance between the scheduler and a broker
stops being structural. Until then the remaining code is a wire, not a design.

### Files touched
NEW: global_index/track1_planned_stop.py,
     scratch/test_track1_stage5zn_planned_stop_lifecycle_20260826.py
MOD: global_index/track1_paper_order.py, track1_order_state.py, track1_order_journal.py,
     track1_paper_executor.py (**BOOK_PATH corrected**), run_live_day_track1.py,
     track1_report.py, scratch/test_track1_stage5x_..., scratch/test_track1_stage5v_...,
     docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

### Liveness
The dashboard's `lifecycle` block appears after a **backend restart** (not performed).
Everything else is importable now; nothing in production imports the order path, by design.

---

## Task: Stage 5ZO - live bar pull proof
Status: DONE (2026-08-26 ET 02:20-04:20). I RESTARTED NOTHING. NO runtime file written/edited.
No old explanation row rewritten. Nothing backfilled for 2026-08-26.

### The ten answers
1. runtime/live file changed? **NO** (all evidence dirs at baseline mtimes)
2. evidence written to: `global_index/track1_runtime/data_observation/data_observation_YYYYMMDD.jsonl`
3. every future decided slot needs proof? **YES**, once the stream exists that day - **WARN not FAIL**
4. proven: provider, 3 identities, parquet sha, rows fetched/offered/kept, overlap count,
   splice code, frozen + final timestamps, frame size
5. changes decisions? **NO** - reads what the join already recorded, computes nothing
6. old slots: **`pre_observation_schema`** - classified, never accused
7. dashboard: **one line in the EXISTING Operational block**, three shapes
8. orders impossible? **YES**   9. next shadow window READY? **YES**
10. remaining: 5, none a design question

### THE GAP (found in the evidence, not the code)
`global_nkd 2026-08-26` PASSed - 22 slots, all decided - and TRACK1_NKD_0255's explanation row
said `bar_timestamps: []`, `data_time: null`. The ledger proved the slot DECIDED; nothing
proved WHAT IT LOOKED AT. On a route that has never traded those are indistinguishable.
Already provable and NOT re-solved: `data_source_identity` carries `<parquet>:<sha256>` - the
HISTORY side was proven; the LIVE side was not.

### Built
- **`global_index/track1_data_observation.py`**: schema, writer, reader, summary, operator line.
  Reads `JoinedFrame.as_dict()` + the splice report. **Computes nothing** (AST-asserted: no
  signal/detector/sleeve/params import; `instrument_row` calls `as_dict` and no aggregation).
- wired into `observe_live_slot` **AFTER the ledger row and WRAPPED** (both AST-asserted by
  line number) - the ledger row is what the audit counts and diagnostics must never cost it.
- **three write cases**: decided -> full row | refused -> refusal row naming the code
  ("nobody looked" != "we looked and were refused") | never reached either -> **NOTHING**.
- **one field deliberately NULL**: `dropped_open_final_bar` + `not_reported_by_the_join`.
  Nothing in the chain records whether the provider's last bar was still forming. Named, not guessed.
- **no bar arrays, no prices** - a test walks the payload and fails on any list >20 items or
  any non-scalar leaf; one row pinned under 4 KB.
- audit: reason `decided_without_data_observation` (WARN) + 9 summary fields.
- dashboard: `Data: IBKR · NKD · 1186 live bars checked · last 02:55 ET · splice OK` /
  `Data proof: not recorded by this slot version` / `Data refused: overlap mismatch`.

### WHY WARN NOT FAIL
The ledger already proves the slot ran and decided; the observation proves what it saw. A
missing one WEAKENS the evidence without contradicting it, and making it fatal would fail every
window recorded before this stage existed. It stops being tolerable the day an order is sent on
a decision nobody can show the data for - and the READINESS GATE is where that belongs.

### OPERATOR RESTART MID-STAGE (not me)
scheduler **18096 -> 18780 @ 02:09:03**, backend **30604 -> 48760 @ 02:09:16** Calgary.
Checked rather than assumed. Clean: same argv/mode, 45 legacy not scheduled, 11 safety,
5 audit, 70 slots, **the 7 pre-flight days restored**.
**Settles liveness the OPPOSITE way from my first assumption**: my edits landed 02:03-02:06,
the restart came 02:09, so everything was picked up. Verified against the LIVE API:
5ZL regime_verify ✓ | 5ZM reporting ✓ | 5ZO data line ✓ | scheduler `--verify-strict` ✓.
The slot writer needs no restart (slots are fresh subprocesses) -> the next window writes real rows.

### Tests: 34. Regression **709 passed, 0 failed**.
Three worth naming: the **end-to-end wiring test** (a `root` param was added purely so one
could exist - a mechanism nobody has watched run is a trap this project has paid for twice);
the **ordering test** (AST line numbers prove the row is written after the ledger row); the
**payload walk** (fails on anything list-shaped enough to be bar data).

### REMAINING BEFORE PAPER (5)
| # | item | class |
|---|---|---|
| 1 | machine sleep | **operator** |
| 2 | B1 account decision | **operator** |
| 3 | five clean judgeable days | time, once 1 is fixed |
| 4 | the regime gate's first PASS | time - **`--verify-strict` is now LIVE** |
| 5 | broker stop proof, partial fills, order in flight across a restart | **paper only** |
Plus the residual: nothing records whether the provider's last bar was open. Small stage, not
a blocker - it means asking the provider layer a question it does not currently answer.

### Files touched
NEW: global_index/track1_data_observation.py,
     scratch/test_track1_stage5zo_live_bar_pull_proof_20260826.py
MOD: global_index/run_live_day_track1.py, global_index/track1_shadow_acceptance.py,
     monitor/backend/job_journal_reader.py,
     docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

---

## Task: Stage 5ZZZ-Q - live Swing detector now reads the CAUSAL D-1 label
Status: DONE (2026-08-29). **NO ORDERS.** approval unset - no orders dir - scheduler pid 3000 and
backend pid 10136 NOT restarted - **zero broker calls** - gates/thresholds/params untouched -
PAPER_SHADOW_EVIDENCE not marked satisfied.

### CONSTRAINT CONFLICT - ASKED, NOT GUESSED
The brief required fixing the live Swing path AND said "do not edit runtime trading files"; the
fix is one line inside `track1_live_source.py`. **Asked the operator, who authorised the live fix
and the evidence fields.** All edits below follow that authorisation.

### THE FIX
`track1_live_source._swing_candidates`:
    before  detect_entry_for_slot(frame, **labels**, ...)      -> labels.get(day) = session's OWN
            row -> **None at 14:05** -> refused EVERY session, while the outer gate had passed
    after   swing_labels = RegimeLabels(pd.Series(labels)..., **lag_days=1**)
            detect_entry_for_slot(frame, **swing_labels**, ...) + stash diagnostics with it
Not a new rule: it is what the NKD path 40 lines above already passed and what the artifact
regeneration already wraps. **Outer gate and detector now read the same object.**

### PROVEN FROM THE CALL (detector intercepted on the live path)
    LIVE Swing 2026-08-28   MES/MNQ/MYM/M2K -> RegimeLabels(lag=1), resolved 'Calm'
    LIVE NKD                MNKD            -> RegimeLabels(lag=1), resolved 'Calm'  (unchanged)
    before the change the same call resolved **None**
    independent: on **190/190** floor sessions where the labels disagree, the object returns the
    PREVIOUS session's value, 0 mismatches

### EVIDENCE FIELD ADDED
`SignalRow.regime_basis`, default `""` so pre-stage rows stay readable and are NEVER assumed to
match. Values from a map **checked against the live call sites by test**, never from the sleeve
name: nkd/swing/calm `causal_d1`, stress `intraday_basket_gate`.

### PARAMS HASH - STAYS EMPTY, HONESTLY
5ZZZ-P flagged it blank. The cause is a CONTRACT, not an oversight: `route_params` refuses a
config missing any of its **27** fields, and one is `data_source_identity = path:sha256` of the
parquet. Hashing a multi-GB file per slot would put real work on the decision path - the same
reason `_signal_data_identity` records the path alone. **A cheap hash would be the partial
identity that module forbids.** Helper now returns empty deliberately, says why, and points at the
explanation record which already writes the full identity. **This caps a post-fix slot at UNKNOWN
until parity joins it from there - named, not papered over.**

### REPRODUCTION - baseline unchanged
Artifacts byte-identical (2474723814ae3e92 / c27ca3902b116912 / 1ee198a9f10387c8).
    full stack  66,796 / 16,181 / 8,105      risk-clean  57,289 / 12,419 / 7,077   ALL MATCH
The live change cannot reach the artifact path (deploy_sim -> SwingTFEngine, not the live source)
- verified, not assumed. SWING_TF_PARAM and NormalR4Params byte-for-byte as before.

### PARITY
New verdicts **PRE_FIX_MISMATCH** (row disagrees with today's code, yesterday's code wrote it) and
**NOT_APPLICABLE** (field did not exist). **Neither is a PASS; old evidence is never rewritten.**
The 08-28 Swing row is now PRE_FIX_MISMATCH. Whole run still NOT_YET_OBSERVED x4 - no session
since the fixes. **Next post-fix Swing slot CAN pass the basis check**; full-slot PASS still
blocked by the params-hash gap.

### TESTS - 14 new, **134 regression, 0 failed**
Restated, NOT deleted (4): 5ZZZ-G's "who decided?" guard **INVERTED** - Swing must now KEEP the
causal object and NKD must never lose it (the operator decided, today, on the record, after
5ZZZ-H measured the cost); the payload test now asserts the two sleeves **AGREE**, because
removing that disagreement at source was the point; the reconstruction-mirrors-live test follows
the new path; 5ZZZ-P's "cannot reach PASS" replaced by recorded-basis-can-pass +
NOT_APPLICABLE + contradiction cases.

### ⚠ WHAT THE OPERATOR SHOULD HOLD IN VIEW
Live Swing **used to refuse every session** because its detector resolved no label. **It will now
decide.** Orders remain impossible so nothing can be sent - but the sleeve's shadow decisions, the
input to PAPER_SHADOW_EVIDENCE, change from "always refuse" to "actually deciding" from the next
session. **This is the first change in the sequence that alters what the live route DOES rather
than what it records.**

### Files touched
global_index/track1_live_source.py (the fix), global_index/track1_signals.py (+regime_basis),
global_index/run_live_day_track1.py (SLEEVE_REGIME_BASIS, honest params-hash),
monitor/backend/track1_market_view.py (reconstruction mirrors live),
global_index/track1_replay_parity.py (PRE_FIX_MISMATCH / NOT_APPLICABLE),
scratch/test_track1_stage5zzzq_swing_causal_d1_live_20260829.py,
scratch/track1_stage5zzzq_swing_live_causal_d1_identity_20260829.{md,json}
**No gates. No thresholds. No params.**

## Task: Stage 5ZZZ-P - live-vs-replay parity: all four sleeves NOT_YET_OBSERVED
Status: DONE (2026-08-29). **READ-ONLY.** No orders - approval unset - no orders dir - scheduler
pid 3000 and backend pid 10136 NOT restarted - **zero broker calls** - runtime trading files,
strategy logic, params and gates ALL untouched - **nothing wired as a gate, nothing marked
satisfied**.

### VERDICT: all four sleeves `NOT_YET_OBSERVED`   (PASS 0 · FAIL 0 · UNKNOWN 0 · NOT_YET 4)
  newest live slot ran   **2026-08-28T12:46:22**
  newest relevant fix    **2026-08-29T00:35:14**   (live_source 00:35, diagnostics 00:33,
                          run_live_day 08-28 18:31, normal_r4 08-28 18:11)
  -> nothing has run since the fixes; today is Saturday.
  **Corroboration, arrived at independently**: `global_index/track1_runtime/strategy_diagnostics/`
  **does not exist** - the store 5ZZZ-B wired would have been created by the first post-fix slot.

NOT_YET_OBSERVED is NOT a soft pass. A slot older than the code it should exercise proves nothing.

### THE HARNESS - `global_index/track1_replay_parity.py` (read-only)
  live   track1_runtime/signals/*.jsonl + shadow_intent/ (Calm)
  replay track1_market_view._strategy(...) for NKD/Swing/Stress ·
         track1_strategy_diagnostics.calm_blocks(...) for Calm
  **Reuses the existing reconstruction on purpose** - 5ZZZ-B/G established it mirrors the live
  call sites. Two implementations would compare the implementations, not the route.
  Verdicts PASS / FAIL / UNKNOWN / NOT_YET_OBSERVED. **A partial match is UNKNOWN, never PASS.**

### PRE-FIX INFORMATIONAL RUN (counts for NOTHING)
  NKD UNKNOWN · Stress UNKNOWN · **Calm UNKNOWN but BOTH phase-isolation checks PASS**
  (DECIDE carries no OBSERVE-only value, no price level) · **Swing FAIL**

### F1 - THE FINDING (material)
  `swing_regime_basis_is_causal_d1` -> **FAIL**
     declared paper identity (5ZZZ-O record): **causal_d1**
     live detector actually reads:           **"this session's own label"**
  **Nuance that must not be lost**: the ARTIFACT/BACKTEST identity IS genuinely causal D-1 -
  5ZZZ-N proved it on **147/147** label-change sessions. The LIVE DETECTOR path is not. The
  signed record describes the former. Changes no number, does not invalidate the override, but an
  operator reading "causal D-1" in the trail should know the live path does not yet read that way.
  Same open finding as 5ZZZ-G (declined there: touches a runtime trading file). Now it has a
  check that keeps saying so.

### EVIDENCE GAPS - all reported AS gaps, none fixable from the reading side
  F2 `params_hash` **empty on every live row** -> no slot can PASS that field
  F3 live row has **no regime-basis field** -> **NKD and Swing cannot reach PASS at all today**,
     even with everything else agreeing. Pinned by its own test.
  F4 data identity spelled two ways (full path vs basename). Compared on the FILE NAME, because
     **a false FAIL is worse than an honest UNKNOWN - someone acts on it.** Inconsistency
     reported rather than hidden by the fix.

### TESTS - 19 passed
matching slot PASSes (so PASS is reachable) · params-hash mismatch FAILs · MISSING hash is
UNKNOWN · data-identity mismatch FAILs · same file two ways does not · unreconstructable is
UNKNOWN · **partial match is UNKNOWN not PASS** · older-than-fixes is NOT_YET_OBSERVED · Swing
same-day basis FAILs, lagged PASSes · Calm OBSERVE-leak and price-level in DECIDE FAIL, clean
DECIDE passes · NKD/Swing capped at UNKNOWN until basis recorded · no write path, no broker/order
reference · never claims to satisfy shadow evidence · gates do not import it · the real run
reports no post-fix slot.
**Self-correction**: the first "fully matching passes" fixture used NKD, which STRUCTURALLY cannot
reach PASS. The premise was wrong, not the tool - retargeted to Stress and the gap pinned as F3.

### COUNTS TOWARD PAPER_SHADOW_EVIDENCE: **NO**
Nothing wired as a gate; the tool declares `counts_toward_paper_shadow_evidence: false` as a
field; and NOT_YET_OBSERVED is the opposite of evidence.

### WHAT WOULD MAKE IT ANSWERABLE
One Track 1 session after 2026-08-29T00:35 - i.e. **Monday** - plus the live writer recording
`params_hash` and the regime basis on the row it already writes.

### Files touched
global_index/track1_replay_parity.py (new, read-only),
scratch/test_track1_stage5zzzp_replay_parity_20260829.py,
scratch/track1_stage5zzzp_live_execution_replay_parity_20260829.{md,json},
scratch/track1_stage5zzzp_parity_raw_20260829.json
**No runtime trading files. No strategy logic. No params. No gates.**

## Task: Stage 5ZZZ-O - Swing paper override moved into the route's decision trail
Status: DONE (2026-08-29). **NO ORDERS.** approval unset - no orders dir - scheduler pid 3000 and
backend pid 10136 NOT restarted - **zero broker calls** - confirmation untouched - runtime
evidence untouched - **strategy logic, Swing params, WFO artifacts and gates ALL untouched**.

### WHAT WAS ADDED
  new   track1_swing_paper_override.json               the record
  new   global_index/track1_swing_paper_override.py    read-only reader; **grants nothing**
  edit  global_index/track1_paper_readiness.py         renders it **ABOVE** the legacy B1 block

### MEASURED BEFORE THE MODULE EXISTED (this is what makes "grants nothing" a fact)
  may_enable_orders -> False · blocking -> ['PAPER_SHADOW_EVIDENCE']
  gates source mentions any swing override -> **False** · record file present -> False

### THE RECORD
  decision_type swing_paper_scope · decision INCLUDE_SWING_IN_PAPER_BY_OPERATOR_OVERRIDE
  confirmed_by kevindo290 @ 2026-08-29 · route track1_candidate · sleeve roska4_swing
  regime_basis causal_d1 · selected_identity D1_OLD_EFFECTIVE_EMA50
  parameter_promotion **false** · evidence_promotion **false** · risk_acceptance **true**
  source_stage 5ZZZ-N · baseline_reference -> the canonical 5ZZZ-N JSON
  caveats (VALIDATED, not decorative - dropping ANY one refuses the record):
    same-day Swing not live-tradable · Swing 2026 contribution negative ·
    no-Swing risk-adjusted OOS better · no bootstrap yet

### IT GRANTS NOTHING - measured three ways
  AFTER the record: may_enable_orders False · blocking ['PAPER_SHADOW_EVIDENCE'] - **IDENTICAL**
  1. the object reports grants_orders / satisfies_shadow_evidence / is_parameter_promotion /
     is_evidence_promotion = False, valid or not
  2. a test asserts `track1_gates` source contains NO reference to the module
  3. **strongest**: a test MOVES the record aside, re-asks may_enable_orders() and blocking(),
     restores it, and requires the answers to be identical
  A valid record and a corrupt one grant the same thing. Only the operator message differs.

### FAIL-CLOSED ON
absent · unreadable · not an object · any missing required field · wrong schema/decision/
decision_type/route/sleeve/regime_basis/selected_identity · unsigned · empty confirmed_at ·
**claiming parameter_promotion or evidence_promotion** · risk_acceptance not true · any caveat
dropped · expired (expires_at optional, enforced when present)

### PAPER SCOPE - all four sleeves IN, evidence PENDING on all four
  NKD / Stress / Calm -> basis `in_scope_by_route_design`
  **Swing -> basis `operator_override`, risk_accepted true, evidence_promoted false,
  parameter_promoted false**
  With the record removed Swing STAYS in scope but falls back to route design and
  risk_accepted becomes false - the sleeve does not vanish, the override stops being claimed.

### VALIDATION
  `scratch/test_track1_stage5zzzo_swing_override_20260829.py` **43 passed**; with the 5ZZZ-N
  canonical suite **64 passed**.
  **Mutations 10/10 RED**: allow a promotion claim · tolerate a dropped caveat · accept unsigned ·
  claim to grant orders · claim to satisfy shadow evidence · ignore route/sleeve mismatch ·
  honour an expired record · report Swing as evidence-promoted · trim caveats from the
  rendering · bury the block under B1.
  **Harness note**: it reported `restored byte-identical: NO` for the new module. Cause was LINE
  ENDINGS (LF -> CRLF on the read/write round-trip), matching the package's existing CRLF
  convention. Content verified unchanged, no mutation text surviving, all 64 tests pass.
  Recorded rather than ignored - a restore check is only worth having if its one firing is
  explained.

### SAFETY (measured at close)
  orders_possible **False** · blocking ['PAPER_SHADOW_EVIDENCE'] (B1 closed again on baseline age)
  confirmation present, approves no orders · swing override present, valid, grants nothing
  orders dir ABSENT · TRACK1_ORDERS_APPROVED unset · broker calls 0
  scheduler pid 3000 track1-only-shadow · backend pid 10136 - neither restarted

### Files touched
track1_swing_paper_override.json, global_index/track1_swing_paper_override.py,
global_index/track1_paper_readiness.py (presentational only - `swing_override_lines`),
scratch/test_track1_stage5zzzo_swing_override_20260829.py,
scratch/track1_stage5zzzo_swing_paper_override_decision_trail_20260829.{md,json}
**No gates. No strategy logic. No Swing params. No WFO artifacts.**

## Task: Stage 5ZZZ-N - canonical baselines REPRODUCED, Swing in paper by operator override
Status: DONE (2026-08-29). commit 601970bf97e23b200b8eb06cbcf22a240897133a / future/incorporation
**NO ORDERS.** approval unset - no orders dir - scheduler pid 3000 NOT restarted - backend pid
10136 NOT restarted - **zero broker calls** - confirmation untouched - runtime evidence untouched
- live route params untouched - SWING_TF_PARAM unchanged.

### FINAL LABELS
  TRACK1_REFERENCE_BASELINE_REPRODUCED · LIVE_TRADABLE_BASELINE_REPRODUCED
  INCLUDE_SWING_IN_PAPER_BY_OPERATOR_OVERRIDE · NO_SWING_PARAMETER_PROMOTION
  PAPER_NOT_READY · NO_ORDER_ACTIVATION

> **Swing is included in paper scope by explicit operator risk acceptance, using causal D-1
> old/effective ema=50. This is not an evidence-based parameter promotion. Same-day Swing remains
> reference-only and not live-tradable.**

### PART A - historical reference REPRODUCED 30/30 (replayed, not regenerated)
  full stack  floor 74,410 (1.67/2.12/2.14/4,973) · 2025 16,997 (2.26/2.76/4.45/3,901)
              · 2026 9,288 (1.62/2.47/3.41/4,342)
  risk-clean  floor 64,903 (1.62/2.34/1.92/4,845) · 2025 13,236 (2.00/2.96/3.09/4,632)
              · 2026 8,260 (1.55/2.57/2.75/4,797)
**These are SAME-DAY numbers and must NEVER be quoted as the paper baseline.**

### PART B - live-tradable selected baseline REPRODUCED FROM CODE (regenerated + replayed)
  artifacts byte-identical to the existing D-1 arm:
      floor 2474723814ae3e92 · vault2025 c27ca3902b116912 · vault2026 1ee198a9f10387c8
  **effective params (sidecar, every window)**: asked ema=30 -> **effective ema=50 SUBSTITUTED**,
      stop_basis 2.0, ratchet False, chandelier_affects_decisions False
  **regime basis PROVEN**: RegimeLabels(lag_days=1); on **147/147** floor sessions where the
      same-day and previous-day labels DISAGREE the object returned the previous day's value.
      0 mismatches. (The regen's own probe landed on an agreeing day and proved nothing - so a
      separate proof was written.)
  numbers, all matched:
      full stack  66,796 / 16,181 / 8,105      risk-clean  57,289 / 12,419 / 7,077
      Swing       +18,429 / +3,906 / **-464**
  **baseline artifacts sha256 BEFORE == AFTER** (regen restores from backup; verified by hash).

### PART C - 8 variants in one canonical table (in the .md/.json)
  1 same-day reference (NOT tradable) · **2 D-1 old/effective ema=50 - SELECTED** · 3 D-1 narrow
  retune (rejected) · 4 full-grid winner (**converged onto #2, identical artifacts**) · 5 prevbar
  (not promoted) · 6 SPY proxy (rejected) · 7 ES proxy (rejected) · 8 no-Swing control.
  Unmeasured cells marked `not_measured` - NEVER filled with zeros.

### PART D - the override is recorded WITH what it overrides
  Stage L's pre-committed thresholds, scored against the selected arm:
      T1 PASS · **T2 FAIL (2026 Swing -$464)** · **T3 FAIL (Calmar 42% of no-Swing in BOTH OOS)**
      · T4 PASS · T5 PASS (5/10)
  **Two of five fail.** Inclusion is an operator decision taken with that on the record.
  Selected because it is the current effective route identity AND the 48-candidate causal-D-1 WFO
  converged back onto it. WFO remains the validation framework for future Swing changes.

### PART E - paper scope: all four sleeves IN, all four evidence PENDING
  NKD · Stress · Calm (two-phase) · Swing (by override, causal D-1 effective ema=50)

### PART F - safety, measured
  orders_possible **False** · blockers ['B1_broker_account_or_legacy_retirement',
  'PAPER_SHADOW_EVIDENCE'] · confirmation present (confirmed_by kevindo290) and **approves no
  orders** · orders dir ABSENT · TRACK1_ORDERS_APPROVED unset · **broker calls 0** · scheduler
  pid 3000 track1-only-shadow · backend pid 10136. B1 reopened on account-baseline record AGE -
  the documented 5ZZZ-E timer, not this stage.

### PART G - validation
  `scratch/test_track1_stage5zzzn_canonical_baseline_20260829.py` **+ 5ZZZ-M suite = 38 passed**.
  Pins: JSON parses · same-day marked not tradable · selected identity effective ema=50 ·
  requested AND effective both recorded · reference and live-tradable are separate sections ·
  risk-clean reference NOT mislabelled D-1 · inclusion is override not promotion · no parameter
  promotion · orders never stated possible · floor IN-SAMPLE, 2025/2026 OOS, 2026 PARTIAL ·
  no unmeasured value silently filled · document matches the running system.

### REMAINING BEFORE PAPER ORDERS
  1. PAPER_SHADOW_EVIDENCE satisfied by real shadow sessions across all four sleeves
  2. B1 closed on a fresh account baseline record
  3. the operator override recorded in the route's OWN decision trail, not only in this report

### Files touched
scratch/track1_stage5zzzn_canonical_strategy_baseline_reproduction_20260829.{md,json},
scratch/track1_stage5zzzn_regime_basis_proof_20260829.{py,json},
scratch/test_track1_stage5zzzn_canonical_baseline_20260829.py,
scratch/normal_promotion_trades_*_d1repro_20260829.json + .params.json sidecars,
scratch/track1_stage5zzzh_full_replay_{base,d1repro}_20260829.json,
scratch/track1_stage5zzzh_swing_d1_regen_20260829.py (regime-basis proof recording)
**No live route code. No engine. No params source. No gates.**

## Task: Stage 5ZZZ-M - the Swing artifact param "disobedience" was a silent SUBSTITUTION
Status: DONE (2026-08-29). **NO ORDERS.** approval unset - no orders dir - scheduler NOT restarted
(pid 3000) - no broker - confirmation untouched - **no live route params changed, SWING_TF_PARAM
untouched, no gate opened**. Baselines byte-identical (asserted by test).

### ROOT CAUSE - `scratch/harness.py`, inside patched_engine's replacement engine
      apply_fixes = (not cfg.roska4_only) or (ema_period == 30)
      if cfg.ema is not None and ema_period == 30:
          ema_period = cfg.ema            # cfg.ema = 50
and `normal_promotion_regen_audit_20260821.py` builds `Cfg(..., ema=50, stop_basis=2.0)`.
**A request for ema=30 is REWRITTEN to 50.** Everything else passes through.
So "ema=30 default" and "ema=50" are **THE SAME RUN**, not two runs that coincide.
**The parameter was never disobeyed. Nothing recorded that it had been translated.**
-> a REPORTING defect, not an engine one.

### PROVEN by four traced regenerations (vault2026)
  A ema30/2.5 -> effective 50 -> sha 1ee198a9f10387c8   MES/MNQ/MYM/M2K = 21/18/23/19
  B ema50/2.0 -> effective 50 -> sha 1ee198a9f10387c8   21/18/23/19   (== A)
  C ema10/2.0 -> effective 10 -> sha b878f9fd39cb7171   22/20/24/23
  D ema20/2.0 -> effective 20 -> sha ef3ef40d10f36315   22/19/24/23
  (+ ema50/mult2.5 also = 1ee198a9f10387c8 -> the chandelier is a no-op here)

### THE NINE ANSWERS (short)
1 reaches entry point YES (recorded at the call site) · 2 reaches the artifact engine YES - and
that is WHERE the substitution happens · 3 reaches the detector YES, with the substituted value ·
4 **ema30 and ema50 are NOT equivalent - they were never both run** · 5 cache = `_swing_cache`,
key `id(df)`, holds only price-derived series (daily ATR, day list, per-day OHLC, per-day 5m);
**key complete for its contents, NOT the cause** - asserted by AST + behaviourally · 6 metadata did
**NOT** record effective params (artifact carried argv only) - **this was the real gap** ·
7 digest changes for ema (10/20/50 distinct); NOT for chandelier, and that is CORRECT (ratchet
False + stop_basis 2.0 -> the multiple only reaches the strategy config) · 8 see below ·
9 next = the range_max/rel_volume_max pass 5ZZZ-L could not reach, then a day-level bootstrap.

### FIX - additive only
Sidecar `<artifact>.params.json` records asked vs effective ema, whether it was substituted, the
stop basis, ratchet, and whether the chandelier affects decisions. NOT added to the artifact
itself - those are hash-pinned baselines and a new key would break every reproduction.
5ZZZ-L's guard CORRECTED: it compared hashes and fired on a true equivalence; it now asserts
artifacts match **iff** the effective params match.

### RECORD CORRECTION - nothing measured is invalid; the LABELS were wrong
  "D-1 old params, ema=30" (5ZZZ-H/I/L)   -> actually **effective ema = 50**, stop basis 2.0
  "narrow retune ema=10" (5ZZZ-I)          -> genuinely ema=10, correct as measured
  "WFO winner ema=50/mult=2.0" (5ZZZ-L)    -> **the same config as the D-1 old arm**
  5ZZZ-L "numbers could not be produced faithfully" -> **WITHDRAWN**, they can
  5ZZZ-L "5ZZZ-I is provisional"           -> **LIFTED**, its comparison stands
**Neither 5ZZZ-I nor 5ZZZ-L needs a rerun** - both needed this label correction.
Also: **`SWING_TF_PARAM`'s ema=30 is NOT what the Track 1 artifacts run.** They run 50 =
`NormalR4Params.ema_period`. The substitution exists to make the Rổ 4 basket run Track 1's period.

### 5ZZZ-L's THRESHOLDS NOW SCORED (winner IS the D-1 old arm, proven by identical artifacts)
  T1 net vs D-1 old        PASS  identical in all 4 OOS cells
  T2 Swing >= $0 both OOS  **FAIL**  2025 +$3,906, **2026 -$464**
  T3 Calmar vs no-Swing    **FAIL**  42% in 2025 (3.36 vs 8.05), 42% in 2026 (3.76 vs 8.92)
  T4 MaxDD <= 115%         PASS  identical
  T5 fold stability        PASS  5/10, five consecutive
-> **still not promoted, now on EVIDENCE not a blocked apparatus.** Cleaner headline for 5ZZZ-L:
the 48-candidate causal-D-1 search **converged on the configuration the route already runs.**

### Tests + mutations
`scratch/test_track1_stage5zzzm_param_obedience_20260829.py` **17 passed**.
**Mutations 6/6 RED**, files restored byte-identical: effective-reported-as-requested · sidecar
echoes the request · threshold moved off 30 · chandelier claimed to matter · substitution hidden ·
cache holds a param-dependent series.
Self-correction: one test scanned `_swing_cache`'s whole source for "chandelier" and matched the
**docstring**; rewritten as an AST walk with the docstring stripped - same trap as 5ZZZ-G.

### Files touched
scratch/track1_stage5zzzm_param_trace_20260829.{py,json},
scratch/test_track1_stage5zzzm_param_obedience_20260829.py,
scratch/track1_stage5zzzh_swing_d1_regen_20260829.py (effective_params + sidecar + fixed guard),
scratch/normal_promotion_trades_vault2026_m_*_20260829.json, *.params.json sidecars,
scratch/track1_stage5zzzm_swing_artifact_param_obedience_20260829.{md,json}
**No live route code. No engine. No params source.**

## Task: Stage 5ZZZ-L - full 48-candidate WFO under causal D-1; blocked by an apparatus defect
Status: DONE (2026-08-29). **NO ORDERS.** approval unset - no orders dir - scheduler NOT restarted
(pid 3000) - no broker - confirmation untouched - **no live route code changed, SWING_TF_PARAM
untouched, no gate opened**. Baseline artifacts restored byte-identical (sha256).

### DECISION: `KEEP_RESEARCH_ONLY`
The wider grid found a **more stable optimum the old grid could not reach**:
  **ema=50, chandelier=2.0, hold=5 - 5/10 folds (50%), five CONSECUTIVE** (vs 5ZZZ-I's 4/10 + tie)
It **cannot be promoted**: the artifact-regeneration path cannot be shown to honour the parameter
it is given, so the OOS evidence the promotion bar needs cannot be produced honestly.

### TWO APPARATUS FINDINGS (both new, both matter beyond this stage)

**1. The tuning engine != the artifact engine.**
`SwingTFEngine.backtest` imports `futures._validated_core.backtest_swing_tf` -> that makes the
artifacts. `pooled_swing_wfo.py` AND Stage 5ZZZ-I used `futures.swing_tf_harness.backtest_swing_tf`.
Different objects, measurably different behaviour (MES, floor, D-1):
    ema30/2.5  vc 555t $7,855.72   harness 564t $10,015.76   +$2,160
    ema10/2.5  vc 556t $13,269.01  harness 563t $14,742.88   +$1,474
    ema50/3.0  vc 503t $5,854.15   harness 509t $6,811.41    +$957
This stage tuned on `_validated_core`. Likely explains why 5ZZZ-I could not reproduce the frozen
ema30/mult2.5 provenance - the ORIGINAL tuning ran on the research engine too.

**2. The regeneration does not reflect the parameter it is given.** (BLOCKING)
Override moved onto `SwingTFEngine.backtest` (the method that READS the params) and the run now
RECORDS what the engine got: `(50, 2.0, 5)`. Artifact still byte-identical to the ema=30 default,
**over the 7-year floor, ~190 trades/instrument**:
    floor      d1 ema30/2.5 = 2474723814ae3e92   d1f ema50/2.0 = 2474723814ae3e92  IDENTICAL
               d1r ema10/2.5 = c504a83b82c57de9  different
    vault2026  ema30=ema50(m2.0)=ema50(m2.5) = 1ee198a9f10387c8 · ema20 = ef3ef40d10f36315
               ema10 = b878f9fd39cb7171
ema 30 and 50 give the SAME artifact; 10 and 20 give different ones. Suspected locus: the regen
installs its own engine via `patched_engine(Cfg(..., ema=50, stop_basis=2.0))`. **Mechanism NOT
resolved.** I did not report full-stack numbers from a path I cannot show obeys instructions.
**Guard added**: the regen now aborts if an override yields an artifact identical to the default.
**Consequence: Stage 5ZZZ-I's retuned arm is now PROVISIONAL.**

### PRE-COMMITTED (written before any OOS number) - scratch/track1_stage5zzzl_precommit_20260829.md
Grid: ema {10,20,30,50} x mult {2.0,2.5,3.0,3.5} x hold {3,5,10} = **48** + vol_feature
{slot20, prevbar}. NOT searched: range_max/rel_volume_max (planned 2nd pass, **not reached**),
stop_basis_atr_mult + spy_short_filter (belong to track1_normal_r4's replay, NOT this artifact
path), fill law/ratchet/arm_hours (fixed or unreached).
Thresholds T1-T5 committed. **T5 MET (5/10). T1-T4 NOT EVALUABLE** - blocked by finding 2.

### WFO OBSERVATION worth keeping
Every fold winner used mult in {2.0, 2.5}; **8 of 10 used mult=2.0 - a value the old grid did not
contain** (it started at 2.5). The previous search excluded the region its own objective prefers.

### ONLY MEASURABLE ARM: vol_feature (a bucket swap, no override needed)
  full stack        floor(IS)     2025(OOS)    2026(OOS)
  same-day (ref)      74,410       16,997        9,288
  D-1 old             66,796       16,181        8,105
  D-1 narrow (prov.)  64,374       10,040        6,946
  **D-1 + prevbar**   64,477     **17,758**      6,918
  no Swing            49,414       12,377      **8,731**
Prevbar is the **only arm ever to beat the same-day reference OOS** (2025: $17,758 vs $16,997,
Swing +$5,483, MaxDD $3,402 < D-1's $4,915) - and it is worse than D-1 old AND worse than no-Swing
in 2026 on every risk metric. One good window, one bad - the same instability as every prior arm.

### BEFORE THIS CAN BE SETTLED
1. Find why the regen ignores ema=50 and ema=30 alike while responding to 10 and 20
2. Re-run 5ZZZ-I's retuned arm (provisional until then)
3. Then judge ema=50/2.0/hold=5 against T1-T4, and run the range_max/rel_volume_max 2nd pass
4. **No bootstrap was run** - with 43-62 Swing trades per OOS window nothing here is tested
   against noise

### Files touched
scratch/track1_stage5zzzl_{precommit,full_wfo,make_volfeature_arm}_20260829.{md,py,json},
scratch/normal_promotion_trades_*_{d1pb,d1f,t50m25,t20m25}_20260829.json,
scratch/track1_stage5zzzh_full_replay_d1pb_20260829.json,
scratch/track1_stage5zzzh_swing_d1_regen_20260829.py (override moved to the read site + proof +
identical-artifact guard), scratch/track1_stage5zzzl_swing_full_wfo_causal_d1_20260829.{md,json}
**No live route code. No engine. No params source.**

## Task: Stage 5ZZZ-K - ES intraday proxy label-recovery: coverage fixed, idea still fails
Status: DONE (2026-08-29). Label-recovery test ONLY - no backtest, no promotion.
**NO ORDERS.** approval unset - no orders dir - scheduler NOT restarted (pid 3000) - no broker -
confirmation untouched - runtime evidence untouched - **read-only over data, no live code changed**.

### DECISION: `ES_PROXY_NOT_PROMISING`
ES fixed the DATA problem and did not fix the IDEA.

                        D-1 persistence   ES pre-14:00 proxy   diff
  floor 2018-2024 (IS)       91.5%              81.9%         -9.6
  **2025 OOS**               87.6%              82.4%         -5.2
  **2026 OOS**               87.3%              75.9%        -11.4
  ALL                        90.6%              81.4%         -9.2
Promotion bar clause 1 (**must beat D-1 OOS**) FAILS in both OOS windows -> no backtest warranted.

### COVERAGE - the one thing SPY could not do
  ES_continuous_1m_8y.parquet  3,375,148 bars  2017-01-02 .. 2026-08-28
  floor 1,736/~1,763 = 98.5% · 2025 250/~251 = 99.6% · 2026 158/~158 = 100.0%
**Timezone settled by MEASUREMENT**: index is naive UTC. Localise UTC -> 80.3% of volume in RTH,
peak in the closing hour. Localise ET -> 42.6%, peak overnight. (Two loaders disagreeing about a
clock has already cost this repo once.)

### CAUSAL - yes, by construction
Cut 14:00 ET. gap · ret_to_1400 · ret_open_to_1400 · range_to_1400 · **overnight_range (ES-only,
18:00 prior -> 09:30)** · rvol_1400 · vol_ratio(shifted) · rvol_5d_prior · absret_5d_prior.
The predicted session's 16:00 close is NEVER read. Walk-forward refit every 126 sessions on
strictly-prior data. Labels follow the route's per-window fit convention (floor 2022-12-31,
2025/2026 2024-12-31) so no later fit leaks backwards. No OOS leakage.

### DECOMPOSITION - same shape everywhere
                D-1 wrong  fixes    D-1 right  breaks    net
  floor            115      58        1,243     189     -131
  2025              31      13          219      26      -13
  2026              20      13          138      31      -18
2026 is where it fixes the MOST (65%) and still loses by 11.4 pts.

### NORMAL DETECTION - the state Swing trades. WORSE everywhere.
              D-1 prec / rec      proxy prec / rec      delta
  floor       0.918 / 0.917       0.839 / 0.803        -0.080 / -0.114
  2025        0.863 / 0.871       0.765 / 0.897        -0.098 / +0.026
  2026        0.889 / 0.889       0.710 / 0.978        -0.179 / +0.089
OOS it buys a little Normal RECALL and pays much more Normal PRECISION - the worst trade for a
single-regime sleeve. **2026**: proxy called Normal on 124 sessions - 88 Normal, **32 Calm**, 4
Stress; **never predicted Stress at all**; Calm recall collapsed to 0.500. The sleeve would have
traded 32 Calm sessions it should have sat out, in eight months.

### TWO INSTRUMENTS NOW AGREE - the limit is not the instrument
  SPY floor: D-1 91.6% vs proxy 82.8%      ES floor: D-1 91.5% vs proxy 81.9%
The target is DEFINED by the 16:00 close, so a 14:00 vantage is two hours short by construction,
and the label is persistent enough that yesterday's answer is very hard to beat. Adding the
overnight session - real information SPY has no access to - moved nothing.

### NOT CLOSED (each is a minutes-long recovery test, NOT a backtest)
- a later cut (15:30/15:55): closer to the close, still causal - but not for a 14:05 sleeve
- predict the sleeve's OUTCOME instead of the label: skips the two-hour gap entirely
- a precision-weighted objective: give up recall on purpose instead of by accident

### TOOLING FAILURE RECORDED
First run reported **zero usable sessions in all three windows**. Not a data finding - an empty
result, and an empty result means suspect the instrument first. Cause: the overnight join grouped
on `.values`, stripping the tz; every reindex against the tz-aware session index gave NaN and the
final dropna emptied the frame. Fixed + two assertions added so it fails loudly next time.

### Files touched
scratch/track1_stage5zzzk_es_proxy_label_recovery_20260829.py + .json,
scratch/track1_stage5zzzk_es_intraday_proxy_label_recovery_20260829.{md,json}
**No live route code. No engine. No params source. Read-only over data.**

## Task: Stage 5ZZZ-J - causal pre-14:00 SPY regime proxy for Swing: closed, in-sample
Status: DONE (2026-08-29). **NO ORDERS.** approval unset - no orders dir - scheduler NOT restarted
(pid 3000) - no broker - confirmation untouched - **no live route code changed, no gate opened**.
Baseline artifacts restored byte-identical (sha256).

### DECISION: `KEEP_RESEARCH_ONLY`
The proxy fails **IN-SAMPLE**, before the missing OOS data becomes the binding constraint. Two
independent failures, either one sufficient:
  1. **Worse than D-1 at its own job**: recovers the same-day label **82.8%** vs D-1's **91.6%**
  2. **Loses money on the window it was built on**: Swing contributes **-$2,433** on the floor and
     the whole route ($45,603) is BELOW the no-Swing route ($49,414)

### DATA - the gate, measured first
  504,239 SPY 5-min bars over 1,999 sessions, **2017-01-03 .. 2024-12-30**
  floor 2018-2024   1,748 sessions, 1,732 with a ~14:00 bar (~1,763 expected)   OK
  2025 OOS          **0 sessions**                                              INSUFFICIENT
  2026 OOS          **0 sessions**                                              INSUFFICIENT
Promotion required beating D-1 OOS and matching no-Swing OOS. **Neither was measurable.**
ES intraday DOES cover all windows (3,375,148 bars to 2026-08-28) - not substituted, see below.

### PROXY IS CAUSAL (by construction)
Features all close by 14:00 ET: gap · ret_to_1400 · ret_open_to_1400 · range_to_1400 · rvol_1400 ·
rvol_5d_prior (shifted) · absret_5d_prior (shifted). The predicted session's 16:00 close is NEVER
read. Walk-forward refit every 126 sessions on everything strictly before; first ~18 months are
warm-up with no prediction, carried into the backtest rather than papered over.

### WHY IT FAILS - the decomposition, not just the number
  D-1 WRONG on   115 sessions   proxy fixes 48.7%  ->  +56 sessions
  D-1 RIGHT on 1,255 sessions   proxy keeps 85.9%  -> -177 sessions
                                                net  -121 sessions
  check: 1255 - 121 = 1134;  1134/1370 = 82.8%  ✓
**Structural, not a tuning problem.** The label is DEFINED by the 16:00 close, so a 14:00 vantage
is two hours short by construction; and the label persists at 91.6%, so persistence is a very
strong baseline that intraday movement actively degrades.

### FULL STACK, floor (the ONLY measurable window - IN-SAMPLE)
  full stack:  same-day 74,410 · D-1 66,796 · retuned 64,374 · **proxy 45,603** · no-Swing 49,414
  risk-clean:  same-day 64,903 · D-1 57,289 · retuned 54,867 · **proxy 36,096** · no-Swing 39,907
  Swing$ under proxy: **-2,433**   Swing taken/rej 386/182 (vs 545/190 same-day)
The 18-month warm-up hole is NOT the explanation: no-Swing refuses on EVERY session of all seven
years and still finishes $3,811 ahead. What sank it is the trades it took, not the ones it missed.

### Why ES was not substituted
It would remove the data obstacle, but the floor result says the obstacle is not the instrument -
same 2-hour gap, same persistent baseline, same underlying. If it needs confirming, run it as a
**label-recovery test first** (minutes), not a backtest (an afternoon).

### Caveats
One proxy design (multinomial logistic, 7 features) · floor is IN-SAMPLE and the only measurable
window - **the proxy's P&L must never be quoted as OOS** · 18-month coverage hole means the trade
count is not like-for-like · no bootstrap, nothing tested against noise.

### Files touched
scratch/track1_stage5zzzj_{spy_intraday_inventory,proxy_agreement,make_proxy_labels}_20260829.py,
scratch/track1_stage5zzzj_{proxy_agreement,proxy_labels,compare}_20260829.json,
scratch/normal_promotion_trades_floor_proxy_20260829.json,
scratch/track1_stage5zzzh_full_replay_proxy_20260829.json,
scratch/track1_stage5zzzh_swing_d1_regen_20260829.py (added --proxy-labels),
scratch/track1_stage5zzzh_full_replay_20260829.py (skips windows an arm cannot cover, says so),
scratch/track1_stage5zzzj_swing_intraday_spy_proxy_20260829.{md,json}
**No live route code. No engine. No params source.**

## Task: Stage 5ZZZ-I - Swing retuned under causal D-1; the retune made it WORSE out-of-sample
Status: DONE (2026-08-29). **NO ORDERS.** approval unset - no orders dir - scheduler NOT restarted
(pid 3000) - no broker - confirmation untouched - **no live route code changed, no gate opened**.
**Baseline reproduced 30/30. Baseline artifacts restored byte-identical (sha256).**

### DECISION: `KEEP_RESEARCH_ONLY`
Best causal D-1 params found: **ema=10, mult=2.5, max_hold=5 - 4/10 folds (a plurality, unstable)**.
That choice is **worse OOS than the params it replaces**. Swing stays enabled in shadow; NOT
paper-orderable. Nothing promoted, so `SWING_TF_PARAM` untouched and no identity doc rewritten.

### FOUR ROUTES, full stack (Calm-NKD ON)
                              floor(IS)        2025(OOS)       2026(OOS)
  same-day (NOT live-tradable)  74,410          16,997           9,288
  D-1, old params               66,796          16,181           8,105
  D-1, RETUNED                  64,374          10,040           6,946
  no Swing                      49,414          12,377         **8,731**
Risk-clean: 64,903/57,289/54,867/39,907 · 13,236/12,419/6,279/8,616 · 8,260/7,077/5,918/7,703

### SWING'S OWN CONTRIBUTION - negative in BOTH OOS windows once causal
                  floor      2025      2026
  same-day      +25,677    +4,690      +719     <- not live-tradable
  D-1 old       +18,429    +3,906      -464
  D-1 retuned   +16,883    -2,190    -1,623

**In 2026, no-Swing beats every live-tradable Swing route on net, PF, Sharpe, Calmar AND drawdown.**
In 2025 no-Swing gives up $3,804 net and buys PF 3.01 vs 2.05, Sharpe 3.90 vs 2.50, MaxDD $1,568 vs
$4,915. The one thing Swing clearly does is carry the IN-SAMPLE floor ($25,677) - the window its
parameters were chosen on.

### NEW FINDING - the frozen parameter's provenance does not reproduce
`futures/basket.py` credits `ema30/mult2.5` to "pooled WFO winner, 5/6 folds" via
`pooled_swing_wfo.py`. Running that protocol reproduces the **fold geometry exactly (6 folds)** and
NOT the parameter:
  fold vote, original config          -> ema10/2.5 (2/6); frozen pair wins 1 of 6
  pooled region Calmar, original cfg  -> ema10/2.5 (1.81); frozen pair 4th (1.11)
  pooled region Calmar, Track1 floor  -> ema20/2.5 (1.35); frozen pair 3rd (0.91)
**"Could not be reproduced", NOT "is wrong".** Independent of the causal question; needs an owner.
Consequence: this stage does not claim to have re-run the original tuning - it is a controlled A/B,
one protocol applied identically to both label sets.

### Selection instability (stated BEFORE any performance number)
No parameter wins a majority in either arm. Control (same-day) has a two-way TIE at 4/10. The frozen
ema30/mult2.5 is picked 1/10 same-day and 2/10 under D-1. The winning param changes almost every
fold and one D-1 fold is negative.

### NOT `DROP_SWING` - and the case for it is now materially stronger
2 OOS windows (one is 8 months / ~45 trades) · no bootstrap, nothing tested against noise · grid is
9 points in 2 dims, never included max_hold or the context filter · selection unstable under BOTH
labels. What would settle it: causal-label selection over a wider grid incl. hold cap and filter,
day-level bootstrap on the OOS windows, threshold pre-committed.

### Files touched
scratch/track1_stage5zzzi_{swing_wfo,make_noswing,compare}_20260829.py + .json,
scratch/normal_promotion_trades_*_{d1r,noswing}_20260829.json,
scratch/track1_stage5zzzh_full_replay_{d1r,noswing}_20260829.json,
scratch/track1_stage5zzzh_swing_d1_regen_20260829.py (added --ema/--mult/--suffix),
scratch/track1_stage5zzzh_full_replay_20260829.py (any-arm --variant),
scratch/track1_stage5zzzi_swing_d1_wfo_retune_20260829.{md,json}
**No live route code. No engine. No params source.**

## Task: Stage 5ZZZ-H - full candidate remeasured with Swing on a causal D-1 label
Status: DONE (2026-08-29). **NO ORDERS.** approval unset - no orders dir - scheduler NOT restarted
(pid 3000) - no broker - confirmation untouched - runtime evidence untouched.
**Baseline reproduced 30/30. Baseline artifacts restored byte-identical (sha256 verified).**

### DECISION: `NEEDS_RETUNE`
Same-day Swing is **not live-tradable**, so the choice is D-1 or nothing - not same-day vs D-1.
Under D-1 the sleeve is weaker in every window and **negative in the newest OOS window**, but its
parameters AND its context filter thresholds were chosen while the same-day label was in play.
Not good enough for paper as it stands; not established as worthless either.

### THE NUMBERS (net delta is the SAME dollar figure under both policies - the arithmetic check)
  full stack, Calm-NKD ON        baseline -> D-1            delta
    floor 2018-2024 (IN-SAMPLE)  +74,410 -> +66,796       -7,613  (-10.2%)
    2025 (OOS)                   +16,997 -> +16,181         -817  ( -4.8%)
    2026 through 08-19 (OOS)      +9,288 ->  +8,105       -1,183  (-12.7%)
  risk-clean, no Calm-NKD
    floor                        +64,903 -> +57,289       -7,613  (-11.7%)
    2025                         +13,236 -> +12,419         -817  ( -6.2%)
    2026                          +8,260 ->  +7,077       -1,183  (-14.3%)

### SLEEVE CONTRIBUTION - Stress and NKD move by EXACTLY ZERO in all six cells
    floor   Swing 25,677 -> 18,429  (-7,248)   Calm -365   Stress 0   NKD 0
    2025    Swing  4,690 ->  3,906  (  -784)   Calm  -32   Stress 0   NKD 0
    2026    Swing    719 ->   -464  (-1,183)   Calm    0   Stress 0   NKD 0
**Swing turns NEGATIVE in 2026 under a causal label.** Calm moves via same-symbol interaction -
real, not leakage.

### THE ROW THAT JUSTIFIES NOT JUDGING A SLEEVE ALONE
2025: **+$1,081 BEFORE portfolio caps, -$784 AFTER them.** Reading the sleeve standalone would
have inverted the sign of the answer.

### Swing churn (filtered bucket)
    floor  shared 633  -119 +136  churn 28.7%
    2025   shared  71   -34  +34  churn 48.9%
    2026   shared  59   -22  +22  churn 42.7%
Ordering DID change: floor taken +6/rej +8, 2025 +1/+2 (family_rej +2), 2026 -2/+2. double_booked=0.

### Self-checks that had to pass (and did, all three windows)
- NKD trade list **byte-identical** (it never goes through the patched seam)
- at least one R4 instrument **did** change (otherwise "no difference" is a no-op)
- argv identical, slippage identical, baseline sha256 unchanged

### Why "worse" was expected, and what it does NOT prove
Same-day reads a label built from the 16:00 close to gate a 14:00-15:55 entry - six hours of the
future. The decline measures **how much the baseline was flattered**, not that D-1 is bad. It does
NOT settle whether the sleeve is good under D-1: this run puts **new labels through an old filter**,
because the filter thresholds were fit under same-day too.

### RECOMMENDATION
**Disable Swing in the paper route; re-run the selection under causal labels before reconsidering.**
Disabling is operationally neutral - Stage 5ZZZ-G measured that live Swing already refuses every
session. Re-running the selection is NOT curve fitting: the original was made on an information set
the live route cannot have. No parameter values proposed.

### Caveats
floor is IN-SAMPLE (largest delta, weakest evidence) · 2026 is 8 months / 45 taken trades, no CI ·
context filter inherited from the same-day fit · one regen per window, no bootstrap ·
**a concurrency mistake** produced a spurious baseline floor of $66,796 when the replay was re-run
while the regen was overwriting shared artifacts - caught by sha256, repeated cleanly, 30/30 back.

### Files touched
scratch/track1_stage5zzzh_{swing_d1_regen,swing_churn,full_replay,compare}_20260829.py,
scratch/normal_promotion_trades_{floor,vault2025,vault2026}_d1_20260829.json,
scratch/track1_stage5zzzh_full_candidate_swing_d1_remeasure_20260829.{md,json},
scratch/combined_repaired_replay_20260822.py (additive per-cluster P&L accumulator ONLY - proved
harmless by re-running and matching all thirty baseline numbers)

## Task: Stage 5ZZZ-G - Swing's regime object: half the premise held, so half the fix was made
Status: DONE (2026-08-29). **NO ORDERS.** approval unset - no orders dir - scheduler NOT restarted
(pid 3000) - no broker - confirmation untouched - **gates/thresholds/schedules unchanged**.
**18 new + 184 regression passed. 8/8 mutations red. NO detector argument changed.**

### THE ANSWER - the proposed fix was NOT made, and why
  CONFIRMED    outer live gate uses `causal_regime_label`; inner detector calls `labels.get(day)`;
               Swing IS handed the raw map and therefore sees the session's own row - which does
               not exist during the session
  NOT SUPPORTED  "Track 1 Swing identity is D-1/causal". The Swing BACKTEST runs the same
               `labels.get(day)` on the same raw map. `track1_normal_r4.generate` says it in
               words: "R4 reads the SPY labels directly ... MNKD reads them through
               RegimeLabels(lag_days=1)"

**Switching would BREAK parity, not restore it.** Measured by running the sleeve's own backtest
twice over the full store, identical but for the labels object:
      raw  186 trades  -4,345.29        lag1  191 trades  -7,401.32
      44 entries only in raw · 49 only in lag1 · 142 shared
The two objects disagree on **238/2175 days = 10.9%**.

### The real defect is the mirror image
BACKTEST reads a label built from D's close to decide D's 14:00 entry - information from after
the decision. LIVE gets None and fails closed. **Live is the honest one; the backtest is the one
that cannot be reproduced.** `causal_regime_label`'s own docstring calls it "six hours of the
future" and guards the OUTER gate only.

**Live impact NOT measurable**: swing has produced no signal in any shadow session, but regime
was Calm throughout and the sleeve trades Normal - it would have refused either way. Confound is
total; no live impact claimed.

### What WAS implemented (safe half, also asked for)
Diagnostics report which regime object the detector was handed:
      global_nkd    "previous session (lag 1)"    Regime = Calm
      roska4_swing  "this session's own label"    Regime = Unavailable
- DERIVED from the object's own `lag`, never from the sleeve name (a hand-written map goes stale
  and then says the opposite of what the detector saw)
- the Regime row equals the detector's regime GATE value, not a second display lookup
- absent rather than guessed when no caller supplied it
- guard test fails if any sleeve swaps its object, carrying the 44/49 number in its message

### Mutation note
M2's anchor matched **2x** -> reported HARNESS BROKEN, never a pass. Retargeted, then red. 8/8.

### DECISION LEFT OPEN - operator's, it moves a gate
  A  make Swing causal D-1 and re-earn the numbers (93 of 235 entries move)
  B  keep the identity; live Swing refuses whenever D's row is missing (a rule live cannot run)
  C  settle whether D's row can legitimately exist before 14:05 (the earlier partial-bar question)

### Files touched
global_index/track1_strategy_diagnostics.py, monitor/backend/track1_market_view.py,
global_index/track1_live_source.py (descriptive string only - passes the labels object it already
held into the diagnostics stash; NO detector argument changed),
scratch/test_track1_stage5zzzg_swing_d1_regime_20260829.py,
scratch/track1_stage5zzzg_swing_d1_regime_detector_consistency_20260828.{md,json}

## Task: Stage 5ZZZ-F - the panel was contradicting itself, and the payload proved it
Status: DONE (2026-08-28). **NO ORDERS.** approval unset - no orders dir - scheduler NOT restarted
(pid 3000) - no broker - confirmation untouched - **gates/thresholds/schedules unchanged**.
**38 new + 301 regression passed. 12/12 mutations red. No runtime trading file modified.**
**BACKEND RESTART REQUIRED** (pid 44968 serves the module it imported at startup) - not done here.

### THE ANSWERS
  NKD / Swing show    trend filter - close - price vs EMA - daily ATR - volume + ratio -
                      regime - setup state - nearest miss
  Stress shows        four gate metrics + trigger / planned stop / session open, muted while
                      unarmed, and **the hour the gate was decided**
  Calm shows          DECIDE and OBSERVE as two cards in their own band, each with its source
  Regime shows        label - posterior - confidence - runner-up - lead - entropy - both model
                      inputs - **and the absent shift threshold, named again**
  Frontend computes?  **Nothing strategy-like.** Asserted three ways and by mutation
  Layout 375/720/1440 **Passes**, after two real overflows were fixed
  Behaviour changed?  None. No gate, order path, or runtime trading file
  orders_possible     False - blocked by PAPER_SHADOW_EVIDENCE

### The finding the stage opened on
Measured, not read: Stress published a trigger at 29,592.50, a stop at 29,652.62 and a session
open at 29,615.25, and the chip directly above them said **"Strategy levels unavailable"**. The
note was computed from the signal rows - where levels came from before the diagnostics stages
published them elsewhere - and had gone on answering a question now answered somewhere else.
Three states are kept apart now: armed / computed-but-not-armed / none at all.

### Also republished
- every strategy block declares its `diagnostics_source` at the top (it was one level down, so
  an unlabelled reconstruction read as a recorded one)
- the Stress gate states the hour it was decided at, from the detector's own `setup_time`
- the regime panel names its absent shift threshold again - the only surviving mention was a
  fallback that never renders, because the record always supplies the field it falls back from

### Two real layout defects (and one this stage caused)
- plot height came from content: populated 437px vs empty 116px. Fixed box; residual 1.5px
  ATTRIBUTED to the card head's line box, not tolerated
- the legend added 40px to a populated tab only - overlaid inside the box
- a chip carrying a sentence could not wrap, overflowing at 375. Fixed WITH `box-sizing:
  border-box` - max-width on a content box = 100% PLUS padding, the Stage 5ZZR trap
- **self-inflicted**: the decision hour pushed the card head 20px past its box at every width;
  a flex item will not shrink below its own text

### 19 stale tests restated - 14 selectors/wording, 5 that were RIGHT
The five caught: chart height, legend height, absent threshold, gate decision hour, and the
60-day regime run's dimming (reset by a rule whose comment covers height and gap and says
nothing about opacity - the tell that it was collateral). Two claims deliberately changed and
stated: the strip legend printed "Crisis" for a THREE-state model; and one fixture was feeding
the page pre-5ZZM wording then demanding the page not show it.

### Four mutations came back green - that was the useful part
M7 a text slice could not tell inside-the-div from after-it · M8 `calm.error` appears twice so
the substring outlived the branch · M11 removed one of the two rules the fix is made of ·
M12 both phases present, so a cross-phase fallback could never fire. Three tests rewritten to
measure the DOM, a missing-phase fixture added, one mutation retargeted -> **12/12**.
Then the new spill check failed on its OWN instrument: tooltips are overlays, legitimately wider
than their anchor. Confirmed by measuring - stripping `.has-tip` took a head from 484 to 462.

### STILL OPEN - reported, NOT concluded
**Swing's detector reads day D's own regime label, which cannot exist in its 14:05-15:55 window.**
NKD reads through a deliberate one-day lag; Swing gets the raw map and the detector does
`labels.get(day)`. The map's last entry at 23:34 ET on 08-28 was **08-27**. `causal_regime_label`
calls reading that row "six hours of the future" and guards the OUTER gate only. Raised
2026-08-26 and left unresolved; this advances it by one observation without closing it. Runtime
trading file + live/backtest divergence = its own stage.

Smaller: cold market-view build ~70s (served stale after, background refresh; the frame cannot
be shortened - the trend filter is recursive over full history). One DOM test failed once and
did not reproduce in four later runs - recorded, not dismissed.

### Files touched
monitor/backend/track1_market_view.py, global_index/dash/realtime/{realtime.js,realtime.css,
index.html}, scratch/test_track1_stage5zzzf_market_view_ui_contract_20260828.py,
scratch/test_track1_stage5zz{l,q,r}_*.py (restated),
scratch/track1_stage5zzzf_market_view_ui_contract_cleanup_20260828.{md,json},
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md
**Runtime trading files changed: none.**

## Task: Stage 5ZZZ-E - Calm, published as two phases that cannot see each other
Status: DONE (2026-08-28). **NO ORDERS.** approval unset - no orders dir - scheduler NOT restarted
(pid 3000) - no broker - confirmation untouched - **gates/thresholds/schedules unchanged**.
**33 new + 123 adjacent passed. 6/6 mutations red. No runtime writer added.**

### THE ANSWERS
  DECIDE now publishes    instrument - direction - causal daily ATR - the stop RULE - the stop
                          DISTANCE - risk if taken - the entry reference TIME
  OBSERVE now publishes   instrument - entry reference PRICE - planned STOP - causal daily ATR -
                          stop distance - risk, and only behind a matched DECIDE
  Can OBSERVE leak        No. The split is read off the detector's own two structures at runtime,
    into DECIDE?          not typed into a list, and price levels are gated on the phase itself
  Behaviour changed?      None. No gate, threshold, schedule or trading decision moved
  orders_possible         False - blocked by PAPER_SHADOW_EVIDENCE

### The runtime half already existed
The Calm slot already writes DECIDE at 09:32 and OBSERVE at 10:02, on every path including the
refusals. So this stage is a READER: no runtime trading file was touched. A second writer would
have put two accounts of one phase on disk, and on the day they disagreed nobody could say which
one was the sleeve.

### The line is derived, not hand-drawn
The detector's full-day routine IS its pre-entry routine plus an entry price and timestamp. So
DECIDE-knowable is exactly the pre-entry fields and OBSERVE-only is exactly what the entry bar
adds. A field added to either lands on the correct side without anyone remembering a list.

The open's location within the previous day's range is the trap: it reads like a price feature,
is computed entirely from the 09:30 open, and therefore belongs to DECIDE. Pinned by a test.

### A mutation came back green, and that was the finding
Every test agreed the DECIDE card carried no price level - it carried none because a DECIDE row
on disk happens never to hold an entry-reference block. **The leak was prevented by the data, not
by the code.** One malformed row would have printed a stop price at half past nine. The gate now
names the phase; a test feeds exactly that poisoned row. Asking why a green mutation survived is
what found this.

### Defects found and fixed
- reconstruction used Path without importing it - every replay said "could not be replayed"
- the record was preferred BEFORE the time check, so not_yet_run never fired
- DECIDE price levels were held off by the data rather than by the code (the surviving mutation)
- the page read Calm one level too high; the response is {market_view, regime}

### Four stale assertions restated (the pre-B1 family, fourth time)
Three asserted the signed confirmation file does not exist -> now assert any decision on disk is
SIGNED. One named B1 in the blocking set -> now asserts something is blocking and that it comes
from the registry. B1 opens and shuts with the age of the account baseline record; naming it pins
a state the clock moves, which is what that test's own docstring warns against.

### Still open
- reconstructed DECIDE carries no risk inputs; recomputing them would be a second implementation
  of the sizing, and a second implementation proves nothing
- neither reconstruction path has yet met a Calm day that actually set up - the last one is
  outside the retained bar window

### Files touched
global_index/track1_strategy_diagnostics.py, monitor/backend/track1_market_view.py,
global_index/dash/realtime/{realtime.js,realtime.css,index.html},
scratch/test_track1_stage5zzze_calm_two_phase_diagnostics_20260828.py,
scratch/test_track1_stage5z{u,v,w}_*.py (assertions restated),
scratch/track1_stage5zzze_calm_two_phase_diagnostics_20260828.{md,json},
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md
**Runtime trading files changed: none.**

## Task: Stage 5ZZZ-B - the variables a sleeve decided on
Status: DONE (2026-08-28). **NO ORDERS.** approval unset - no orders dir - scheduler NOT restarted
(pid 3000) - no broker - confirmation untouched - **gates/thresholds/schedules unchanged**.
**31 new + 70 adjacent passed. Decisions proven unchanged.**

### THE ANSWERS
  Written as RUNTIME evidence      NKD + Swing, every slot, **from the next slot onward**
  RECONSTRUCTED for earlier today  NKD + Swing (same 4 variables) + Stress gate/levels
  Still UNAVAILABLE                Calm's two phases; runtime store empty until a slot runs
  Any trading decision changed?    **NO** - asserted, both sleeves, two sessions
  Any gate changed?                **NO** (3 runtime files gained observability-only blocks)
  orders_possible                  **False** (PAPER_SHADOW_EVIDENCE)

### THE SEAM - the detector reports, nothing here computes
`track1_normal_r4` takes an optional **observer**: `detect_entry_for_slot` reports each gate it
passes/stops at, `_scan_window` reports EMA/ATR/avg-volume/regime per bar. Return discarded,
exceptions swallowed **inside** the detector.
**Why not recompute:** the detector's own docstring - *"A second implementation of an entry rule
proves nothing about the first"*. A recomputed EMA would drift from the artifacts.
**Proof decisions unchanged:** with vs without observer, MES+MNKD x 08-27/08-28 -> identical;
and with an observer that **RAISES on every event** -> identical.

### RECONSTRUCTION TODAY (real numbers where 5ZZR could only print "not reported")
  global_nkd   EMA10 66,281.71  close 65,905.00  d -376.71  ATR 105.71  vol 1.63x  Calm
  roska4_swing EMA50  7,754.68  close  7,739.75  d  -14.93  ATR   8.12  vol 1.43x  --
Both no-setup, with the **detector's own reason**: NKD *"regime 'Calm'; this sleeve trades
['Normal']"*; Swing - today's regime is not published until the 13:45 pre-flight adds the SPY row.

### IT STOPS AT NOW
  09:00 -> 0 bars, no last bar | 14:20 -> 3 bars, last **exactly 14:20** | 23:00 -> 22 bars
  a future day -> 0 bars
**Gap found while writing:** the reconstruction hardcoded the present instead of honouring
`build(now=...)` - which would have made "stops at now" **untestable**.

### WHEN A GATE STOPS IT BEFORE THE BARS
The window is walked again through the **SAME `_scan_window`**, deciding nothing, discarding the
result - purely so the four variables show. The refusing gate stays refused and stays reported.
On a Calm morning "this sleeve trades Normal" is complete about the DECISION and tells an
operator nothing about the instrument.

### RUNTIME EVIDENCE
A **third** observability block in the slot, placed/wrapped exactly like 5ZD's signal row and
5ZO's data observation - **after the coverage row**, because that row is what the audit counts.
Append-only, dated. Capture wrapped, write wrapped, observer factory falls back to None if the
module cannot even be imported. **Nothing written yet** - no slot has run since; the dir appears
at the next one (NKD 01:10 Monday). Reader prefers recorded over reconstructed; a day with no
record reads **empty, not an error** - which is what every historical day is.

### CALM LEFT UNWIRED - deliberately
The two-phase contract says DECIDE must never see a value OBSERVE produced, and the live path
reaches the detector **through that contract**, not through `detect_entry_for_slot`. Wiring it
without the phase split would leak exactly what the contract prevents. Same judgement 5ZZP
recorded for the same sleeve.

### A SEVERE REGRESSION I INTRODUCED AND CAUGHT
First working version: **57s per warm request** on a polled endpoint (was ~0.02s).
  read_parquet 3,375,148 rows   0.15s   <- not the problem
  `_cache_for` EMA/ATR pass    14.31s   <- **and not memoised**, called 4x = 57s
**Shortening the frame is not available**: the EMA is recursive over full history, so a truncated
frame gives numbers the detector never saw - and a reconstruction that does not match what the
detector would see is worth nothing.
Fix: **stale-but-usable, refreshed out of band** (the pattern `_running_schedulers` already uses).
  after: cold 66s once, then **0.03s warm**
Key deliberately **STABLE** (sleeve, day, store) - a key with the clock or mtime in it mints a new
key every bar, and a new key has nothing to serve stale, so every append pays the full minute
inline. Second correction: `build()` passed its own derived `ref` instead of the caller's `now`,
so every request looked like a caller naming an instant and **skipped the cache entirely**.

### TESTS CHANGED
3 x 5ZZR tests **superseded** - they asserted these values read "Not reported by detector", which
was an accurate description of the panel **and an indictment of it**. Property kept: a card never
shows a blank - value, or the named reason there is none.
2 x tests **I wrote earlier TODAY** pinned states the clock moves ("Stress/Swing have not run
yet"; an exact failing-checks set that clears when a 5th judgeable day lands). **Third time this
session** - named as a pattern, not three accidents.

### NOT THIS STAGE'S FAILURES
The market-view UI was **rewritten (mv2-* markup) between stages**, before this one began; 5 tests
against the older markup fail on the new Regime Monitor wording, plus the long-standing rule-grid
one. I also wasted a patch matching **remembered** 5ZZR markup rather than the file - the file is
the authority and it had moved.

### SAFETY
A test asserts **by import graph** that track1_gates / track1_paper_readiness /
track1_shadow_acceptance cannot see the diagnostics module: a reconstruction must never satisfy a
readiness gate, an audit verdict or an order gate.

### STILL OPEN
- Calm's two phases (above)
- the **first runtime block lands at the next slot**; that write is not yet exercised end-to-end
- a 66s cold request per 5 idle minutes - bounded, but the real cost is `_cache_for` being
  un-memoised on a 3.3M-row frame; memoising it **inside the detector** would help every caller
- the 5 UI tests against the rewritten market view

### FILES TOUCHED
global_index/track1_strategy_diagnostics.py (NEW), global_index/track1_normal_r4.py,
global_index/track1_live_source.py, global_index/run_live_day_track1.py,
monitor/backend/track1_market_view.py, global_index/dash/realtime/realtime.{js,css},
scratch/test_track1_stage5zzz_b_strategy_diagnostics_20260828.py,
scratch/test_track1_stage5zz{r,z_a}_*.py + 5zzzc (tests restated),
scratch/track1_stage5zzz_strategy_diagnostics_runtime_and_reconstruction_20260828.{md,json},
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md

## Task: Stage 5ZZZ-C - what was underneath the stale reason
Status: DONE (2026-08-28). **NO ORDERS.** approval unset - no orders dir - scheduler NOT restarted
(pid 3000) - no broker - **confirmation file untouched** - **NO audit/runtime/trading file written**
(digests unchanged). **21 new + 408 adjacent passed, 10/10 mutations caught.**

### THE ANSWERS
  2026-08-27 still a FAILED evidence day?  **YES**
  Exactly why?  **roska4_calm and roska4_stress genuinely failed on DATA REFUSALS** - nothing to
                do with the confirmation file
  PAPER_SHADOW_EVIDENCE moved?             **NO** - still False, same four failing checks
  orders_possible                          **False** (PAPER_SHADOW_EVIDENCE)
  Any runtime/audit/trading file written?  **NO**

### 2026-08-27, SLEEVE BY SLEEVE
**roska4_calm - REAL data failure.** observed **0 of 1**; BOTH phases gate_refused:
  DECIDE_0932  missing_session, entry_quote_absent, stale, partial_coverage
  OBSERVE_1002 missing_session, stale, partial_coverage
**roska4_stress - REAL data failure at the window OPEN.** observed **18 of 24**; the six slots
10:35-11:00 gate_refused (missing_session, stale). The other 18 decided normally.
**global_nkd - PASSED ON THE DAY.** Its own row written when the window closed says
`PASS ['all_slots_observed_no_action']`. A later sweep overwrote it, and that sweep's only
failing reason was the removed rule. The readiness reader keeps the **LAST** row per
(scope,sleeve,day) - which is why the gate lists global_nkd as never having passed.
**roska4_swing - NOT RE-JUDGEABLE.** No clean same-day row, and the checkpoint cannot be rebuilt.

### `checkpoint_wrong_day` IS NOT A FINDING ABOUT THAT DAY
The check compares the day under judgment against `live_positions.track1.json` - a **SINGLE LIVE
FILE overwritten on every run**. Measured: `cut_instant 2026-08-28T10:02`, file rewritten 08:02
today, **no dated history anywhere in the tree**. So re-judging ANY past day reports
checkpoint_wrong_day **every time, forever**. A verdict guaranteed regardless of what happened is
not evidence about what happened. Pinned by a test on the file's shape + the absence of history.

### CLASSIFICATION, NOT CORRECTION (task 7)
New **read-only** module `global_index/track1_audit_reinterpretation.py` reports 3 things per
sleeve and **never writes**: stored (verbatim), classification (which reasons came from a REMOVED
rule, and whether the row was failed SOLELY by those), reevaluated (+ whether it is ENTITLED to
say it). The stale registry is **checked against the code**, not trusted.
**That check earned itself immediately:** 5ZZZ-A had removed the rule but left
`reasons.append(R_CONFIRMATION_FILE)` - unreachable only because nothing emits the string it
matches on. Unreachable-by-string is thin, and it made the reason look LIVE to anything reading
the file to learn what the code can produce. **Removed.**

### THE LINE IT DOES NOT CROSS
`track1_gates.shadow_evidence -> track1_paper_readiness -> readiness`. The new module is **NOT on
that path**, asserted by reading the **import graph**, not the comment claiming it. Turning a
stored failure into a pass **moves the only gate still holding this route** - that is an
operator's decision with the reasoning in front of them. And on this day it would change nothing:
two sleeves failed for real.

### NO CORRECTED ROWS WRITTEN (task 6 - allowed only if proven required AND safe; not proven)
Rows are append-only JSONL with provenance (`audit_trigger`, `audit_pid`, `ts`) - a hand row would
carry MY pid and a trigger no other row means. 08-27 fails on merit anyway. 08-28's rows get
rewritten by the scheduled audits. **Digests identical before/after; a test recomputes them.**

### WHAT ACTUALLY STANDS BETWEEN HERE AND PAPER ORDERS
  judgeable_days                    4 of 5      <- **time, not a defect**
  no_failing_days                   4, 0 allowed <- REAL (08-24/25 coverage+schema, 08-26 Calm,
                                                   08-27 the Calm+Stress data refusals)
  calm_decision_evidence            missing 08-24, 08-25 (pre_shadow_intent_schema) <- REAL
  every_sleeve_passed_at_least_once ['roska4_calm','global_nkd'] <- **the one place the removed
                                     rule still costs something** (nkd DID pass on 08-27)

### MUTATIONS - 10/10, mostly WIDENING (the dangerous direction)
register a live reason as stale / dismiss a re-evaluation entitled to speak / wire it into the
gate / let it write. Two narrow it - a classifier that dismisses nothing would satisfy every
safety test and be useless. **Two honest GREENs before retargeting:** one wrote `{} or {...}`
(Python picks the non-empty dict - a no-op); one substituted the re-evaluated verdict into the
stored field, **invisible because every sleeve is FAIL both ways on this day** - now caught by a
synthetic record that makes the two disagree by construction.

### STILL OPEN
- **WHY did the provider have no session at 09:32 and at 10:35 on 08-27?** This stage identified
  the refusals; nobody has asked the next question yet.
- **global_nkd's overwritten PASS** - last-row vs best-row is a real design question, and
  changing it moves a gate, so it belongs to an operator.
- The audit's Calm window still reads `["10:00","10:00"]` and expects 1 slot where 2 phases run.

### FILES TOUCHED
global_index/track1_audit_reinterpretation.py (NEW, read-only),
global_index/track1_shadow_acceptance.py (one unreachable branch removed),
scratch/test_track1_stage5zzzc_shadow_evidence_real_failures_20260828.py,
scratch/track1_stage5zzzc_mutations_20260828.py,
scratch/track1_stage5zzzc_shadow_evidence_real_failures_20260828.{md,json},
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md

## Task: Stage 5ZZZ-A - a signature is not an armed order
Status: DONE (2026-08-28). **NO ORDERS.** approval unset - no --allow-orders - no orders dir -
scheduler NOT restarted (pid 3000) - no broker - **confirmation file NOT deleted** - runtime
trading files untouched. **18 new + 460 adjacent passed, 9/9 mutations, 0 failures caused.**

### THE ANSWERS
  Calm 2026-08-28 turned PASS?   **YES**   (all_slots_observed_no_action, no_candidates_to_explain)
  NKD  2026-08-28 turned PASS?   **YES**   (all_slots_observed_no_action)
  Remaining non-confirmation reason on those two?  **NONE**
  orders_possible still false?   **YES** - PAPER_SHADOW_EVIDENCE throughout
  Runtime trading files touched? **NO**
Stress/Swing -> NOT_ENOUGH_DATA_YET ['window_not_closed'] - correct, their windows (10:35, 14:05)
had not run when the audit was taken.

### THE RULE THAT EXPIRED
`elif confirmation: FAIL "the confirmation file exists during a shadow period"` was TRUE when
written - the signature really was the last thing before an order. Then 5S added a measured
evidence gate, 5ZZK gave B1 a measured half, the operator signed 08-27 and **orders_possible
never became true**. The file now records a DECISION; whether an order could be sent is a
separate question, and the gate is asked it directly.
NEW order gate: order mark -> FAIL | gate says possible -> FAIL | **TRACK1_ORDERS_APPROVED set ->
FAIL (new)** | **order journal dir exists -> FAIL (new)** | signed conf + blocked -> **OK and says so**.
The two new FAILs are not decoration: **the gate registry deliberately does not read the env**
(5ZZS pinned it), so without them an approved shadow run would pass an audit about whether an
order could have been sent.

### WHAT THE STALE RULE WAS COSTING - the part worth reading twice
**1. It MASKED real failures.** 08-27 recorded `['confirmation_file_present']` for all four
sleeves. Re-evaluated with the rule gone:
   global_nkd    checkpoint_wrong_day
   roska4_calm   coverage_incomplete, slot_could_not_evaluate, no_candidates_to_explain
   roska4_stress coverage_incomplete, slot_could_not_evaluate
   roska4_swing  checkpoint_wrong_day
Anyone reading that record would have seen one stale-policy reason and moved on. **Four sleeves
had real problems underneath.** 08-27 still FAILS - and should.
**2. It FED the only remaining blocker.** `shadow_evidence`: *"no_failing_days: 4 FAIL day(s) in
the qualifying window, at most 0 allowed"*. A rule that fails every day from the signature onward
**manufactures the failures that hold the route's last gate shut.**

### AUDIT RECORDS - did NOT append, and why (measured, not cautious)
- 08-28: the audit jobs (03:05/10:10/12:40/16:05/16:15 ET) will write corrected rows today from
  the fixed code. A hand row would carry my pid + an invented `audit_trigger` - not what any
  other row in that file means.
- 08-27: re-evaluates to **FAIL either way**, so a "corrected" row states the same verdict with
  different reasons - it changes no count and no decision.
Stored rows kept as a true record of what the audit said under the old policy. Nothing rewritten.

### MUTATIONS - removing a FAIL is the shape needing the most proof
Most re-arm the route another way (orders possible / approval set / order journal / order mark);
two put the stale rule back. **Two came back GREEN honestly before retargeting:** one dropped a
condition the fixture was flipping in lockstep with another (added a test that flips each alone);
one forced a branch false into an `else` producing the same code.

### 6 STALE TESTS RESTATED across 5 suites (pre-B1 family, 3rd time)
4 asserted the confirmation file does NOT exist -> now assert the things that **ARM** an order do
not exist, and that any decision on disk is **signed**. 2 pinned the exact blocker roster, which
changes with record age and evidence.

### 3 REMAINING FAILURES - measured as NOT caused here
parquet fingerprints/dates pinned against a store that has grown (5zk); fixtures written before
5ZZC changed how the SPY refresh calls `_run` (5zl); job-inventory / preflight pins (5zg, 5zo).

### STILL OPEN
- **08-27 fails for four real reasons now visible for the first time** - 2 checkpoints on the
  wrong day, coverage gaps on Calm and Stress. Worth its own stage; this one only removed what
  was hiding them.
- PAPER_SHADOW_EVIDENCE still 4 judgeable of 5, 4 failing. 08-27 fails on merit; 08-28 should
  stop counting once today's scheduled audits write corrected rows.
- The audit's Calm window still reads `["10:00","10:00"]` from before Calm became two phases -
  coverage passes anyway ("2 of 1 decided") but the expected count is stale.

### FILES TOUCHED
global_index/track1_shadow_acceptance.py (the only production file),
scratch/test_track1_stage5zzz_a_shadow_audit_confirmation_20260828.py,
scratch/track1_stage5zzz_a_mutations_20260828.py,
scratch/test_track1_stage5z{g,h,k,l,o}_*.py (6 stale assertions restated),
scratch/track1_stage5zzz_a_shadow_audit_confirmation_policy_20260828.{md,json},
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md

## Task: Stage 5ZZY - a polled endpoint must not open a console
Status: DONE (2026-08-28). **NO ORDERS.** approval unset - no --allow-orders - no orders dir -
**scheduler NOT restarted (pid 3000 unchanged)** - backend-only restart (brief authorised) -
runtime trading files untouched. **28 new + 681 adjacent passed, 10/10 mutations caught.**

### ITEMS 1-3 WERE ALREADY DONE BEFORE THIS STAGE BEGAN
schedule_status.py + open_issue_reader.py were modified at **08:04** - after 5ZZX finished
(~07:35), before this stage started. `scheduler_track1_mode_status()` existed, both readers used
it, neither called ops. **I verified that work and did items 4, 5, 6.** Recorded because the
alternative is a report that reads as though I wrote all of it.

### THE REGRESSION WAS MINE (5ZZW)
Making the backend ask the SCHEDULER for its mode was right; using `ops.track1_status()` to ask
was not. Measured: **2.84s and 2 x powershell.exe per call.** At an 8s poll that is a console
flashing several times a minute - and **5ZZX's log filters could never have helped, because the
noise was never in the log.** The backend already had a cached psutil scan whose own docstring
says "never call this on a request path".

### A MEASUREMENT I HAD TO THROW AWAY
First probe: **zero** subprocess calls from every endpoint - which would mean no regression at
all. **A zero that convenient is a reason to check the instrument.** A deliberate subprocess.run
proved the spy live; calling ops directly showed the 2 spawns. The endpoints were clean because
the fix was already on disk - not knowable from the zero. Every measurement here now self-checks.

### VERIFIED NO SHELL
20 warm requests across the 4 polled endpoints -> **subprocess x0, powershell x0**.
Mode parsing: `--track1-only-shadow`->0 legacy jobs; **`--track1-shadow`->45** (shares a prefix
with the safe mode and still runs every legacy entry slot); default->45; empty->**unknown, not
legacy**; no scheduler->unknown.

### TASK 6 - THE GREEN TEST WAS WATCHING THE WRONG LANE
The 3 Calm tests had already cleared. Two properties held (TRACK1_CALM_1000 absent from table AND
mirror; both phases mirrored). **The third did not.** The passing test guards the **incidents**
lane (keys on slot_id, never wrong). The **journal + issue** lanes key on job_type, and every
strategy slot shares one:
  TRACK1_CALM_DECIDE_0932 failed 09:32 + TRACK1_STRESS_1035 completed 10:35
  -> **Calm reported `recovered`, recovered_at 10:35**
Same family as 5ZZU - a bucket read as a stream - one layer up, and **the green test could not
have seen it**. Recovery now keys on the **SLEEVE** via `recovery_stream()`, which the issue lane
defers to so the two lanes cannot disagree. `job_type` unchanged - everything asking "is this a
strategy slot" gets the same answer.
  Calm <- Stress: **open** | Calm DECIDE <- Calm OBSERVE: **recovered** (one sleeve's day)
  Swing <- Swing: recovered | NKD <- Swing: open
A mutation splits the stream per SLOT to prove separating sleeves did not separate a sleeve from
itself; another leaks the finer value into job_type to prove that stays clean.

### LIVE VERIFICATION
`ops.py restart --no-scheduler --yes --track1-only-shadow`
scheduler **UNTOUCHED pid 3000** - backend 35956 -> **34664**
**32/32 requests = 200. Shell processes before 24, peak 24, DELTA 0.**
(the 24 includes my own measurement powershell; the delta is what matters)
`ops.py status`: track1_mode=track1-only-shadow - scheduler_mode=compatible - confirmation=True -
legacy_entry_jobs=0 - blocking=['PAPER_SHADOW_EVIDENCE'] - orders_possible=False

### 9 STAGE-5ZZW TESTS MOVED TO THE NEW SEAM
They patched `ops.track1_status` and expected the resolver to consult it - it reads the cached
scan now, so they described a seam that no longer exists. Each keeps its property and asserts it
through `_running_schedulers`. **The retirement fixture now writes its confirmation under
tmp_path**, so those tests can no longer be answered by the production file.

### 1 REMAINING FAILURE - pre-existing, previously measured
`test_40_the_render_path_has_no_rule_grid_left` - rule grid / JSON.stringify in the market-view
render path from 5ZZL/5ZZR.

### STILL OPEN
- **ops.py still shells out, and should** - it is a command-line tool, not a request path. What
  changed is that nothing on a polled path calls it; a test makes any such call an explicit failure.
- the **frontend keeps a fourth recovery lane** (realtime.js, matches on job_type). It only runs
  to NAME the job that recovered one already marked recovered, so with the backend correct it has
  nothing to find - but it is a coarser rule and wants its own pass.
- the pre-existing render-path assertion above

### FILES TOUCHED
monitor/backend/job_journal_reader.py, monitor/backend/open_issue_reader.py,
scratch/test_track1_stage5zzy_dashboard_poll_no_shell_20260828.py,
scratch/track1_stage5zzy_mutations_20260828.py,
scratch/test_track1_stage5zzw_dashboard_track1_mode_hygiene_20260828.py (9 tests reseated),
scratch/track1_stage5zzy_dashboard_poll_no_shell_20260828.{md,json},
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md
(items 1-3 in monitor/backend/schedule_status.py + open_issue_reader.py were already on disk)

## Task: Stage 5ZZX - the console was reporting questions, not answers
Status: DONE (2026-08-28). **NO ORDERS.** approval unset - no --allow-orders - no orders dir -
**scheduler NOT restarted (pid 3000 unchanged)** - backend-only restart (brief authorised it) -
runtime trading files untouched. **31 new + 553 adjacent passed, 10/10 mutations caught.**

### COUNTED THE LOG BEFORE BELIEVING THE FRAMING - 358,361 lines
  GET 200                337,972   **94.3%**   dashboard polling
  GET 3xx                  8,860
  other                    8,036
  WARNING/ERROR            2,806
  "Adding job tentatively"   685   **0.19%**   bursts on SIX distinct days, not continuous
  "slots registered"           2
**The flood is the access log, not APScheduler.** A page polling every 8s writes ~10k successful
GETs a day whether the system is healthy or on fire. An access line records that a QUESTION was
asked, not that anything happened.

### THE APSCHEDULER LINES ARE NOT THIS PROCESS
  07:17:13  Adding job tentatively x7 + slots registered
  07:21:12  monitor.backend.app: **Starting Flask** on http://127.0.0.1:5002
The burst lands **four minutes BEFORE the backend logged its own startup** -> it is `ops.py`
building a scheduler object to enumerate it during a restart, console output to the same file.
Confirmed from the other side: handler attached in-process, **all four endpoints emit ZERO
apscheduler records** and all answer 200.

### THE BACKEND NEVER STARTS A SCHEDULER
AST walk over global_index/ + monitor/: `.start()` on a scheduler appears **exactly once**,
`run_scheduler.py:1942`, in the scheduler's own main. The mirror builds and enumerates; nothing
is started, dry_run=True. Pinned by a test + "scheduler pid unchanged across a request".
**Self-correction:** that test was first a TEXT search and matched **this stage's own docstring**
in app.py - a sentence ABOUT the call counted AS the call. It parses the source now.

### WHAT WAS SUPPRESSED (backend process ONLY, in app.py)
- `_QuietSuccessfulRequests` on `werkzeug` -> drops 200/204/301/302/304 access lines
- `_NoTentativeJobAdds` on `apscheduler` **AND** `apscheduler.scheduler` - a filter on the parent
  is **not consulted** for a record made by a child logger; a mutation checks exactly that

### WHAT IS KEPT (the half that makes it safe)
every 4xx/5xx - every WARNING/ERROR **including on a 200** (level checked first) - tracebacks -
backend startup lines - **"Scheduler started" / "Running job ..."** so a real scheduler here would
still say so - **an access line the filter cannot parse** (an unrecognised line is not a line to
throw away) - **the scheduler's own log, untouched**. Nothing global disabled.

### WHAT I DID *NOT* DO
- **Mirror still builds a real scheduler object.** Replacing it with a hand-written slot list is
  exactly what `scheduler_slot_ids` exists to avoid - its comment says a second list is how the
  two drift apart, and 5ZZT was spent on that class of drift. Costs **2 lines per backend START**,
  not per request.
- **Polling frequency unchanged** (POLL_MS=8000). The brief asked for a measurement first; the
  interval was never the problem - at 0 lines per request the same 8s now costs nothing.

### VERIFIED LIVE
`ops.py restart --no-scheduler --yes` -> scheduler **UNTOUCHED pid 3000**, backend pid 35956.
**40 warm requests across the 4 endpoints -> 40/40 = 200, and ZERO new log lines.**
Only 2 lines written since restart, at 07:31:10 (~60s after start) = the known cold-start warm-up
from 5ZZR. Once per backend start, not per request. Before: those 40 requests = 40+ access lines.

### MUTATIONS - deliberately pointed at the DANGEROUS direction
Most **widen** the filter: drop 404s, drop warnings, drop a real "Scheduler started", throw away
an unparseable line. Two stop it filtering at all. One replaces the whole approach with a global
`logging.disable` - the blunt instrument this stage deliberately did not use. **10/10 caught.**

### 3 REMAINING FAILURES - pre-existing, measured since 5ZZT
All three expect a `TRACK1_CALM_1000` slot / "Calm one-shot band" from before Calm became two phases.

### SAFETY
scheduler pid 3000 unchanged - orders_possible=False - blocking=['PAPER_SHADOW_EVIDENCE'] -
scheduler_mode=compatible confirmation=True legacy_entry_jobs=0 - orders dir absent -
TRACK1_ORDERS_APPROVED unset. Only `monitor/backend/app.py` changed. The restart reconnected the
existing read-only reader the backend always starts (client_id=99); no new connection from my code.

### STILL OPEN
- the 2 construction lines per backend start - honest, removable by extending the existing
  suppression to the `run_scheduler` logger. **Left alone**: 2 lines a restart is not noise, and
  widening a suppression is how a real message goes missing.
- the 3 Calm-band tests above
- the retained log keeps its 358,361 historical lines - **nothing truncated**; the point was to
  stop adding to it, not to delete three weeks of record to tidy a window

### FILES TOUCHED
monitor/backend/app.py,
scratch/test_track1_stage5zzx_backend_console_noise_20260828.py,
scratch/track1_stage5zzx_mutations_20260828.py,
scratch/track1_stage5zzx_backend_console_noise_hygiene_20260828.{md,json},
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md

## Task: Stage 5ZZW - the dashboard was answering about the other route
Status: DONE (2026-08-28). **NO ORDERS.** approval unset - no --allow-orders - no orders dir -
scheduler NOT restarted - backend NOT restarted - no broker call - runtime trading files untouched.
**30 new + 698 adjacent passed, 14/14 mutations caught.**

### ROOT CAUSE - two readers, one machine
`ops.py` reads the **SCHEDULER's command line** (process table). `schedule_status` read **THIS
BACKEND PROCESS's** `RAITS_TRACK1_ONLY`. ops sets that var on both processes when it starts them;
the backend that was serving had been started without it. So the backend answered `legacy` about
a machine running track1-only, and everything downstream followed.

**TWO independent rail triggers, both from that one mismatch:**
- `inactive_by_design=false` -> the Stage 5ZF suppression **never fired**, so the stale legacy
  snapshot (4.2 days - nothing writes it in this mode) raised the page-level alarm
- the slot mirror expected the LEGACY table -> **22 phantom overdue slots**

### AFTER (measured through the endpoints)
route_mode=track1_only_shadow - source=scheduler_process_table - known=true
freshness **stale -> not_expected_yet** - overdue **22 -> 0** - slots **45 -> 71**
legacy_runner.state_stale **still true** - reported as its own line, no longer route health

### WHERE the resolution happens mattered as much as the resolution
First version resolved it INSIDE `get_schedule_status` -> live page right, **26 tests wrong**:
every suite that describes a machine by clearing the env began reading the **real process table**.
A test that is not isolated is worse than no test. So the mode is a **parameter**; `app.py` passes
what the scheduler says, every other caller keeps exactly its old behaviour.
**Unknown is its own answer** - never collapsed into legacy. Mutations for both directions.

### ISSUE PRUNING - needs all THREE, fails toward showing too much
confirmation=True + scheduler_mode=compatible + legacy_entry_jobs=0. Any unreadable -> NOT retired.
**8 -> 6 issues -> 3 active / 3 retired history.** (8->6 was 5ZZU's stream fix merging the SPY rungs.)
Moved to history: the 3 `paper:*` - they compare the **LEGACY** ledger vs broker statements and
read no Track 1 artefact. **Nothing deleted** - every issue travels with `counts_as_active` + reason.

### THE TRAP TASK 4 EXISTS FOR
`known_debt:model_age` was grouped **under Legacy**. Survivable while both were shown; a hazard
the instant the legacy group stopped counting - the model debt would have gone quiet with it.
Now its own **Model / Regime** group, chip reads MODEL not DEBT. 5ZZH's test that asserted it
lands under Legacy now asserts the opposite.

### CACHE DEFECT FOUND BY THE TESTS
Retirement was first computed inside `_build`, which is **memoised** on log signatures + date. A
second read with the opposite answer returned the first from cache. Whether legacy is retired is
a fact about the **running scheduler** and changes with no log line written here - the answer
would have stayed frozen while legacy came back. Applied per read now, outside the cache. The
roll-schedule cache key two lines above carries a comment about the same trap.

### MODEL INPUTS
Read the **legacy runner snapshot** -> in this mode it showed a Regime label from whenever legacy
last ran, presented as today's. Now: Regime + SPY session + fit end + label check all from the
**Track 1 regime record**. `Fit end` turned out to have **no setter at all** - a dead field
showing `--` since it was added. Legacy stays as fallback; panel no longer `runner-derived`.

### WORDING
"Legacy runner snapshot is stale because legacy entries are retired" / "Track 1 scheduler needs
attention" / chip reads "Track 1 scheduler" / "scheduler mode unknown - could not read the scheduler".

### GATES
**PAPER_SHADOW_EVIDENCE is the only Track 1 blocker. orders_possible=False.** Nothing changed.
(B1 blocked for part of the morning - the account baseline passed its 24h policy, see 5ZZU. The
operator refreshed it. That is why tests here assert membership, not the exact blocker list.)

### ADJACENT TESTS TOUCHED
5 deliberate supersessions (debt group, group headings, group list, 13th pre-B1 restatement) +
**1 genuinely pre-existing failure fixed while passing**: the pinned-fact list had been missing
`Blockers come from` since Stage 5ZZK.

### 6 REMAINING FAILURES - all pre-existing, previously measured
3 = Calm slot from before Calm became two phases; 2 = rule grid / JSON.stringify in the
market-view render path (5ZZL/5ZZR); 1 = the intermittent DOM test recorded in 5ZZU.

### BACKEND RESTART **REQUIRED** (not done here)
schedule_status.py + open_issue_reader.py + app.py are imported once per process; backend pid
20212 started 03:13, before all of this, and keeps serving `route_mode: legacy` until restarted.
realtime.js/index.html are static but read fields only the new backend emits.

### STILL OPEN
- the 3 Calm-band tests and 2 render-path assertions above
- ops.py still propagates RAITS_TRACK1_ONLY to backends it starts - now a convenience rather than
  the source of truth for the live page, but a hand-started backend still answers from the env
  for any caller that does not inject the mode

### FILES TOUCHED
monitor/backend/schedule_status.py, monitor/backend/open_issue_reader.py, monitor/backend/app.py,
global_index/dash/realtime/realtime.js, global_index/dash/realtime/index.html,
scratch/test_track1_stage5zzw_dashboard_track1_mode_hygiene_20260828.py,
scratch/track1_stage5zzw_mutations_20260828.py,
scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py,
scratch/test_track1_dashboard_runtime_wiring_20260824.py,
scratch/track1_stage5zzw_dashboard_track1_mode_hygiene_20260828.{md,json},
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md

## Task: Stage 5ZZU - a job may only be closed by another job that did the same work
Status: DONE (2026-08-28). **NO ORDERS.** approval unset - no --allow-orders - no orders dir -
scheduler NOT restarted - backend NOT restarted - no broker call - runtime trading files untouched.
**29 new + 655 adjacent passed, 14/14 mutations caught, 0 failures caused (measured).**

### THE CATCH-ALL HELD MORE THAN THE BRIEF LISTED
Measured from the type map, not the brief: TRACK1_STOP_REPAIR_* (9 weekday + sun_1830),
TRACK1_MAX_HOLD_EXIT, TRACK1_AUDIT_* (5), **and HEARTBEAT**. The classifier had kept them clear
of the legacy prefixes since it was written - but **distinguishable is not the same as typed**.

### THE DEFECT HAD **TWO OPPOSITE** DIRECTIONS - only one was known
- **journal lane**: grouped every catch-all job into ONE stream -> anything completing closed
  anything that failed. Reproduced: audit closed a failed sweep, sweep closed a failed audit,
  audit closed a failed max-hold. (5ZZT saw this in production on 08-27.)
- **issue lane**: `_stream` fell back to the **job id**, so each sweep stood ALONE. A Track 1
  sweep that failed at 06:20 could **NEVER** be closed by the identical sweep at 08:20, while
  its legacy counterpart always could. **Not in the brief - found by reading the second reader.**
One lane gave a false all-clear; the other opened something nothing could ever clear.

### NEW STREAMS
track1_safety_stop_repair - track1_safety_max_hold - track1_window_audit
Both max-hold spellings matched (slot table says `track1_maxhold_exit`, the log label is
`TRACK1_MAX_HOLD_EXIT`) - matching one types the job on some days and not others.
Matching is on the **structured type, never a substring**: TRACK1_STOP_REPAIR_0620 CONTAINS
"STOP_REPAIR", and a substring test would merge the two routes - the one thing B1 keeps apart.

### EVERY "MUST NOT CLOSE" HAS A "MUST CLOSE" BESIDE IT
The lazy fix - stop closing anything - would satisfy half the suite and be **worse** than the
bug, because that is exactly how the issue lane was already broken. **Mutation M8 exists solely
to make that unshippable.** Later sweep DOES close earlier failed sweep; legacy stream untouched.

### WORDING
Audit failure no longer says "unclassified error ... reconcile current broker state" (a job that
never touches the broker). Now: no evidence record was written for that window, nothing at risk
in the book, the paper-evidence gate reads that record. Sweep names the Track 1 book and stops.

### WHAT A TYPE CHANGE COSTS AT ITS CALL SITES
Four readers consume job_type; two needed work. The UI decides scheduler-vs-runner from a list
these jobs were on **only by being untyped** - typing them without naming them there would have
blamed a missed sweep on **a runner that never ran**. And the job id was the row's visible label;
it moved to the tooltip. **Relabel scoped to the three new types only** - the first attempt also
covered strategy slots and the legacy sweep and broke 6 tests in the 5ZE operator view, which
addresses rows by id. Renaming a taxonomy is a design change of its own.

### MY OWN SCOPE ERROR, CAUGHT BY THE SUITE
The label helper landed 3 scopes deep inside a render function -> jobLabel invisible at the
journal row -> panel threw -> **19 tests errored with no .job-row at all**. Same mistake as
5ZZL (render calls inside a click handler). Moved beside mvEsc; the patch now **asserts the
destination brace depth == 1** instead of trusting indentation.

### B1 REOPENED MID-STAGE - NOT CAUSED HERE
`track1_blocking=['B1_broker_account_or_legacy_retirement','PAPER_SHADOW_EVIDENCE']`,
orders_possible **still False**. Root cause measured: `account baseline UNKNOWN
(baseline_record_stale)` - checked 2026-08-27T11:29:47Z, read 2026-08-28T11:31:07Z =
**24h 1m**, so the 24-hour policy expired **81 seconds** before the reading.
**This is the gate working exactly as 5ZZS test_28b demands.**
**OPERATOR ACTION: rerun the account baseline check to close B1 again.** Nothing at risk meanwhile.

It exposed brittleness in tests I wrote YESTERDAY - a live ageing state pinned as an invariant:
- 5ZZT + 5ZZU asserted the blocker list **by equality** -> now `orders_possible False` + `in ids`
- 5ZZS test_28 asserted `b1_decision_evidence is True` -> now a two-valued answer with a reason
- 5ZZS test_28b used "B1 is closed right now" as a **precondition** -> now drives BOTH directions
The 5ZZS mutation harness still catches **11/11** after the rewrite: time-independent, not weaker.
Plus a **twelfth** pre-B1 stale test found in 5ZD (a suite 5ZZS never ran), restated the same way.

### REMAINING 6 FAILURES - measured, none mine
2 = rule grid / JSON.stringify in the market-view render path (5ZZL/5ZZR);
3 = expect TRACK1_CALM_1000 + "Calm one-shot band" from before Calm became two phases;
1 = test_35, **flaky** - passes alone and in a second combined run, failed in neither arm of the
attribution measurement. Recorded as flaky, not fixed.

### REAL DATA
30 Track 1 maintenance jobs across 3 days, all completed, **none carrying a recovery marker**.

### BACKEND RESTART **REQUIRED** (not done here)
job_journal_reader.py + open_issue_reader.py are imported once per process and the backend
started before they were edited. realtime.js is static, but the types it reads come from the
backend - a browser reload alone shows nothing new. A backend-only restart does not touch the scheduler.

### STILL OPEN
- **the account baseline needs rerunning to close B1** (operational, not code)
- HEARTBEAT is still typed `other`; it never reaches the journal so it cannot take part in a
  false recovery today - named so the next reader does not rediscover it
- the two render-path assertions and three Calm-band tests above

### FILES TOUCHED
monitor/backend/job_journal_reader.py, monitor/backend/open_issue_reader.py,
global_index/dash/realtime/realtime.js,
scratch/test_track1_stage5zzu_recovery_stream_isolation_20260828.py,
scratch/track1_stage5zzu_mutations_20260828.py,
scratch/test_track1_stage5ze_job_view_operator_20260825.py (id -> tooltip),
scratch/test_track1_stage5zd_signal_diagnostics_20260825.py (12th pre-B1 restatement),
scratch/test_track1_stage5zf_ops_report_completeness_20260825.py (28/28b made time-independent),
scratch/test_track1_stage5zzt_schedule_mirror_spy_ladder_20260828.py (blocker equality),
scratch/track1_stage5zzu_track1_recovery_stream_isolation_20260828.{md,json},
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md

## Task: Stage 5ZZT - the SPY ladder becomes visible, and a false recovery stops
Status: DONE (2026-08-28). **NO ORDERS.** approval unset - no --allow-orders - no orders dir -
scheduler NOT restarted - backend NOT restarted - no broker call - run_scheduler.py READ ONLY.
**18 new + 407 adjacent passed, 9/9 mutations caught, 0 failures caused (measured).**

### FOUR PARITY TESTS WERE RED, NOT TWO
5ZZS named 2 (in 5L). Running them found 2 more in monitor/test_schedule_status_track1_20260823.py.
All four said: `only_in_scheduler = [spy_last_chance_pre_nkd, spy_refresh_pm_r1, spy_refresh_pm_r2]`
in BOTH modes. 62 compared vs 59 mirror rows (legacy); 132 vs 129 (track1-shadow).

### WHAT THE GAP HAD ALREADY COST - read the journal BEFORE changing anything
**2026-08-27: ALL THREE RUNGS FAILED.** The 00:45 last look on 08-28 completed and fixed the
series - exactly the case 5ZZD built it for. Three defects visible in five lines:
- **FALSE RECOVERY.** R1 and R2 read `lifecycle=recovered, recovered_at=2026-08-27T22:20:14Z`.
  Listing every `other`-typed job that day identifies it: **TRACK1_STOP_REPAIR_1820**, a
  stop-repair sweep. **A sweep of broker stops closed a failed data refresh.** Mechanism:
  `later_same_stream` matches on job_type and both sat in `other`. **A catch-all is not a stream.**
- **USELESS LANGUAGE.** The retries read "unclassified error ... reconcile current broker state"
  - broker advice for a job that never touches the broker.
- **INVISIBLE.** No panel row, so neither the failures nor the recovery could be reported.

### WHAT CHANGED
- 3 rows added to PIPELINE_FIXED_SLOTS, times **READ FROM THE DECORATORS** not assumed:
  r1 16:45, r2 17:15, last_chance 00:45 (all mon-fri).
- The 3 rungs share ONE job_type -> a missed rung caught by a later rung now reads as a recovery
  through the machinery that already existed for stop_repair.
- The last look gets its OWN type: it asks for the PREVIOUS TRADING DAY, not today's close.
  Folding it in would mark an evening rung recovered for a question that rung never asked.
- Language splits on `later_same_stream`, like the stop_repair branch always has. **Conditional
  on purpose:** 5ZZC is titled for the measurement that stopped this ladder becoming an alarm
  nobody reads; copying the 16:20 wording onto the rungs rebuilds that alarm via the missed path.
  Unconditional softening would be the opposite error. **Both directions pinned by tests.**

### THE CHECK PARITY CANNOT MAKE
Parity compares **ids only**. A row at the wrong minute passes it and reports overdue **forever**
- the alarm nobody can silence, which is why 5ZZS refused to add rows without measuring.
New test derives the schedule from run_scheduler.py decorators (AST) and compares CLOCKS both
ways. **Mutation M3 moves r1 one hour early: parity still PASSES, only this test catches it.**

### VERIFIED
parity both modes in_parity=True, both lists empty - 2026-08-27 retries now lifecycle=open,
recovered_at=None - schedule status today: 0 incidents / 0 open / 0 unexplained_overdue / no SPY
row overdue - track1-only state_slot_count=**71 unchanged** - all four shared_infra, none a
strategy slot - orders_possible=False, blocking=['PAPER_SHADOW_EVIDENCE']

### ATTRIBUTION - measured, not guessed
Reverted both edits, re-ran, diffed: **caused 0 - pre-existing 5 - fixed 4**.
The 5 pre-existing: 3 expect a `TRACK1_CALM_1000` / "Calm one-shot band" from before Calm became
two phases, 1 pins the old 70-slot literal, 1 reads the running backend mode.

### BACKEND RESTART **IS** REQUIRED (not done here)
backend pid 20212 started 03:13:01 - schedule_status.py edited 04:52:17 - job_journal_reader.py
04:52:53. A module is imported once per process, so the running backend serves the OLD model.
Verified in-process instead. A backend-only restart does not disturb the scheduler (5ZZO).

### STILL OPEN
- **O1** `other` is STILL a shared stream: TRACK1_STOP_REPAIR_* and TRACK1_AUDIT_* are kept from
  the legacy prefixes on purpose and never got types of their own. All completed today so nothing
  is falsely closed now; the next failed Track 1 sweep will be closed by an unrelated audit.
  **Same defect, different jobs - wants its own stage.**
- **O2** cross-day recovery invisible: the journal reads one day at a time, so 08-27 still shows
  three open failures with no sign of the 00:45 job that repaired them.
- **O3** the five pre-existing failures above.

### FILES TOUCHED
monitor/backend/schedule_status.py, monitor/backend/job_journal_reader.py,
scratch/test_track1_stage5zzt_schedule_mirror_spy_ladder_20260828.py,
scratch/track1_stage5zzt_mutations_20260828.py,
scratch/track1_stage5zzt_schedule_mirror_spy_ladder_20260828.{md,json},
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md

## Task: Stage 5ZZS - post-B1 ops test invariant repair
Status: DONE (2026-08-28). **NO ORDERS.** approval unset - no --allow-orders - no orders dir -
scheduler NOT restarted - backend NOT restarted - no broker call - runtime trading files NOT edited.
**363 passed / 2 failed (deliberate), 11/11 mutations caught.**

### THE TEN WERE **TWO** FAMILIES, NOT ONE
**Six stale pre-B1** - three of them asserting the confirmation file is ABSENT, which is not a
safety claim but a claim that nobody had decided anything; plus B1-in-blocking (5ZZK closed it)
and the file-alone shadow refusal (5ZZN narrowed it).
**Four stale post-refactor, nothing to do with B1** - 5ZZC moved the SPY refresh body into
`_spy_refresh`. test_27 failed saying *"the post-close refresh no longer runs strict, so a drift
exits 0 again"* - which would be serious **if true**. `--verify-strict` is at run_scheduler.py:995,
one call deeper. A test reading one function body cannot survive that body moving.

### REAL DEFECT FOUND (D1) - fixed
`spy_refresh_pm_r1`, `spy_refresh_pm_r2`, `spy_last_chance_pre_nkd` (added 5ZZC/5ZZD) were
**unclassified** in route_classification. The module comment says exactly this should happen -
an unnamed job lands in unclassified and turns a test red until someone names it. **The mechanism
worked; nobody answered it.** Fail-closed throughout: retirement reads only the legacy bucket, so
they were never removable; `_bucket_for('live_day_0935')` = legacy_entry before AND after.
Now declared shared_infra + added BY HAND to 5L REQUIRED_SURVIVORS (that list deliberately does
not derive from the table - an earlier version iterated what it guarded and agreed with it).

### REAL DEFECT FOUND (D2) - measured, NOT fixed, alarm left ringing
Dashboard schedule mirror does not model those same three jobs (schedule_status.py:181 lists only
SPY_REFRESH_PM). `only_in_scheduler = [last_chance, r1, r2]`. Three jobs run nightly and the panel
has **no row** to report them late or missing. Not fixed here: different subsystem, and a row for
a job that does not fire when expected = a permanently-red alarm, the failure this project has
already paid for. Needs its own stage with the cron times MEASURED. The 2 parity tests stay red.

### NEW POST-B1 INVARIANTS (nothing weakened)
- I1 orders impossible and something **MEASURED** holds them
- I2 B1 closed needs a **signature** - remove it, B1 returns
- I3 B1 closed needs a **measurement** - fail it while signed, B1 returns  [test_28b, NEW]
- I4 **no signature and no env var** releases what holds orders  [test_28c, NEW] - never sets
     TRACK1_ORDERS_APPROVED; asserts every holding blocker is MEASURED_GATE with released_by==()
     and the registry never reads the environment
- I5 a confirmation on disk must be **signed** and must not imply orders_possible
- I6 the file ALONE does NOT refuse a shadow start / I7 file + every blocker clear STILL does
- I8 a legacy start IS refused while the decision stands, and the refusal **names the mode that
     is allowed**  [NEW] - narrowing I6 without I8 would have been a straight loss of safety
- I9 shared-infra membership exact BOTH ways against the **production** classifier
- I10 nothing unclassified; counts **derived**, not pinned

### WHAT THE MUTATIONS CAUGHT IN MY OWN WORK (3 honest GREENs)
- **M1** waived the B1 measurement -> whole suite green. test_28 shows the SIGNATURE is
  necessary; I assumed that covered the measurement. It does not - a decision gate reappears
  unsigned whatever the measurement says. **One half of the rule asserted twice.** -> test_28b
- **M6** opened orders on TRACK1_ORDERS_APPROVED -> green. Every test asserted the var was UNSET;
  none asserted what if it were SET. **An assertion about the environment is not one about the
  gate.** -> test_28c
- **M7** broke the `unclassified` fallback -> green, **correctly**: once the three rungs were
  declared, no registered job reaches that line. A mutation on a path the tests never execute is
  not a passing test, it is a mutation that never ran. Retargeted at the opposite direction.
- My own error: asserted `conf.get("confirmed_by")` but that is an **attribute**, not a flag - a
  properly signed decision read as unsigned. Caught on the first run.

### ATTRIBUTION OF 33 WIDER FAILURES - measured, not guessed
Reverted the one production edit, re-ran the same suites, diffed the failure sets:
  pre-existing 29 - caused by me 1 (REQUIRED_SURVIVORS) - **FIXED by me 2** (every_registered_job_is_classified)
Guessing from names would have misfiled `test_b1_still_blocks_orders`, which reads like mine and is not.

### SAFETY AFTER
track1_mode=track1-only-shadow  track1_blocking=['PAPER_SHADOW_EVIDENCE']  orders_possible=False
scheduler_mode=compatible confirmation=True legacy_entry_jobs=0
orders dir absent - live_positions.track1.json absent - TRACK1_ORDERS_APPROVED unset
run_scheduler.py mutations ran on a **COPY** (digest checked before/after): it is a runtime
trading file, and "restored a few seconds later" is no answer when a killed process leaves the
live scheduler's own module broken on disk.

### STILL OPEN
- D2 dashboard mirror does not model the three SPY-ladder jobs
- 29 pre-existing failures in wider slot/scheduler suites (live_day/maxhold_exit aliasing group,
  job-count literals, a rendered-blocker pinning mismatch)
- PAPER_SHADOW_EVIDENCE remains the sole thing between this route and an order - measured, not signable

### FILES TOUCHED
global_index/track1_slots.py,
scratch/test_track1_stage5zf_ops_report_completeness_20260825.py,
scratch/test_track1_stage5k_ops_startup_20260823.py,
scratch/test_track1_ops_status_mode_20260824.py,
scratch/test_track1_stage5s_paper_readiness_20260825.py,
scratch/test_track1_stage5l_shared_preflight_20260823.py,
scratch/track1_stage5zzs_mutations_20260828.py,
scratch/track1_stage5zzs_post_b1_ops_invariants_20260828.{md,json},
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md

## Task: Stage 5ZZR - the Market View stops being one chart, starts being three strategies
Status: DONE (2026-08-28). **NO ORDERS.** approval unset - no --allow-orders - no orders dir -
confirmation untouched - scheduler NOT restarted - no broker call - **0 trading decisions changed**.
**33 new (8/8 mutations caught) + 474 adjacent passed.**

### WHAT THE OLD VIEW ASSUMED, AND WHY IT WAS WRONG
One candle chart per sleeve with entry/stop/target lines, as if all three were price-trigger
strategies differing only in hours. Measured from the detectors:
  NKD    track1_normal_r4  EMA 10  entry_after_setup_only - no standing level exists
  Swing  track1_normal_r4  EMA 50  the SAME detector, slower period
  Stress track1_stress_mnq         metric_boundary - the ONLY sleeve using basket metrics
An earlier draft assumed NKD was basket-driven. It is not; that would have put four numbers on
its panel that its detector never looks at.

### THE CORRECTION THIS STAGE IS ABOUT
5ZZQ recorded "a metric boundary publishes no price level" and pinned it with a test. **Wrong.**
session_context returns pre_low/pre_high for EVERY judgeable session, gate or no gate. On
**2026-08-27, a day the gate FAILED**: trigger **29,575.25**, planned stop **29,662.38**.
Withholding it hid a real number; drawing it solid would have put a tradable line on a dead day.
The rule was never *no level* - it is **no ARMED level**:
  no level published        -> nothing drawn
  published, gate failed    -> dashed + dimmed + "not armed" + a note saying why
  published, gate passed    -> solid amber
5ZZQ test rewritten from price_levels == [] to the no-armed-line rule, carrying the measurement
that disproved it.

### NKD/SWING NOW NAME THEIR OWN FOUR VARIABLES
make_signal_fn(prev_bar, resume_bar, **ema, atr, regime, avgv**) -> Trend filter (EMA 10/50),
Volume vs 10-bar average, Daily ATR, Regime. All say **"Not reported by detector"** - computed
in _scan_window, never returned. Same shape as the Stress rule values before 5ZZP, fixable the
same way. Five missingness answers stay distinct: not_yet / no_record / refused / missing_data /
not_reported_by_detector.

### REGIME - exactly TWO features, and the model keeps its own words
SPY 1-day log return + Realised volatility 5-day annualised. Nothing else (range/SMA/drawdown
are not inputs). Calm, posterior 99.84%, lead 99.67% over Normal, uncertainty 0.018/1.585 bits.
"**No published shift threshold**" - Viterbi compares states to each other, not to a cut.
My first cut **hardcoded that sentence into the page**. That is the drift failure this project
keeps meeting; it now lives in track1_regime_record.NO_THRESHOLD, the page READS it, and the
test asserts the page does **not** contain the words. A fixture holding its own stale
transcription of that string now derives from the constant too.

### WHAT THE TESTS CAUGHT
- **Real layout defect:** max-width:100% on a content-box pseudo-element is 100% PLUS its
  padding and border. At 375px the row is 343 and the tooltip rendered 367 - the 24px is 9/11px
  padding + 1px border each side. Two earlier attempts shrank the overflow without removing it,
  which was the tell that neither had found the cause.
- **Case-sensitive assertion vs a CSS-uppercased heading - FOURTH time.** My own spec had
  already called this a property of the page. Fixed once, by a helper every text assertion uses.

### TEN OPS TESTS ARE RED AND THIS STAGE DID NOT DO IT
5zf / 5k / ops_status_mode assert the **pre-B1** world: that track1_go_live_confirmation.json
does NOT exist and that B1 is still a blocker. Stage 5ZZJ created that file **2026-08-27** as a
deliberate operator decision; 5ZZK closed B1. Evidence it is not 5ZZR: the file predates by a
day; the only ops test reading a file I touched (test_14 on realtime.js) passes; and inside the
failing test_28 the safety assertion `allowed is False` **still passes**. Orders remain
impossible - what is stale is the claim about WHICH gate is blocking.
**Left open and named** - needs its own stage. Ten permanently-red tests are an alarm people
learn to ignore, and quietly editing them inside a dashboard stage would hide that.

### RESTART
Frontend: **no** - static files, no build step, a reload picks them up.
Backend: optional - a running backend holds the old module and shows the previous panel until
restarted. A display lag, not a safety matter. Scheduler: **not restarted, not required.**

### SAFETY AFTER
track1_blocking=['PAPER_SHADOW_EVIDENCE'] orders_possible=False
scheduler_mode=compatible confirmation=True legacy_entry_jobs=0
orders dir absent - live_positions.track1.json absent - TRACK1_ORDERS_APPROVED unset

### STILL OPEN
- NKD/Swing prerequisite VALUES (computed in _scan_window, not returned) - 5ZZP-shaped fix
- Calm two-phase diagnostics: DECIDE at 09:32 must not display OBSERVE values
- per-slot diagnostic persistence
- ~62s first-request cost on a freshly started backend (predates this work)
- the ten stale ops assertions above

### FILES TOUCHED
monitor/backend/track1_market_view.py, global_index/dash/realtime/realtime.{js,css},
global_index/track1_regime_record.py,
scratch/test_track1_stage5zzr_strategy_native_market_view_20260828.py,
scratch/track1_stage5zzr_mutations_20260828.py,
scratch/track1_stage5zzr_strategy_native_market_view_redesign_20260828.{md,json},
scratch/test_track1_stage5zzl_market_view_regime_20260827.py (identifier + wording),
scratch/test_track1_stage5zzq_setup_boundaries_hmm_explain_20260828.py (superseded rule),
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md

## Task: Stage 5ZZQ - setup boundaries + HMM explainability
Status: DONE (2026-08-28). **NO ORDERS.** approval unset · no --allow-orders · no orders dir ·
confirmation untouched · scheduler untouched · no broker call · **0 trading decisions changed**.
**423 passed, 0 failed.**

### SETUP BOUNDARY, PER SLEEVE (proof travels IN THE PAYLOAD)
  Stress  **metric_boundary**        entry_conditions compares 4 basket COUNTS + an avg gap vs
                                     StressParams - **no single price is the trigger**
  NKD     **entry_after_setup_only** detect_entry_for_slot returns SwingSetup or None; the entry
  Swing                              comes from a per-bar signal fn, not a standing level
  Calm    **two_phase**              DECIDE must not show OBSERVE-only values
**NO price line is drawn before a candidate exists.** Drawing one for Stress would put a trigger
on screen the strategy does not have, and somebody would eventually trade against it.

### WHAT STRESS NOW SAYS WHEN IT SAYS NOTHING (2026-08-27)
  below open+VWAP     4  needs >= 4       PASS
  gapped down         0  needs >= 3       **FAIL - 3 more needed**
  wide range          0  needs >= 0       PASS
  avg basket gap +0.51%  needs <= -0.10%  **FAIL - 0.61 pp away**
  -> `No setup · Instruments gapped down 3 more needed` · price_levels **[]**
**NEAREST failure, not first** - declaration order is an accident; the question is how close.
`missing_data` stays distinct from `no setup`.

### WHY THE MODEL SAID CALM - exactly 2 features, named at source
  SPY 1-day log return          +0.65%   77th pct  z +0.72   **no lean**  (sep 0.228)
  Realised vol 5d annualised  5.8% ann.   **0th pct**  z -1.39   **Calm**   (sep 1.083)
  posterior Calm 99.8354% / Normal 0.1643% / Stress 0.0003% · margin 0.996711
  **entropy 0.0176 of 1.5850 bits** · threshold **none**
**The real answer: volatility is at the FLOOR of its 60-day range and nearest Calm's own mean;
the return does not discriminate at all** (the 3 state means sit within a thousandth).
`leans` = distance to a state mean in that state's own sd, **`no lean` below 0.5 separation**.
**NOT an attribution** - a Gaussian HMM decodes a path over a joint distribution and does not
decompose into per-feature contributions.

### A SLOWDOWN I CAUSED - AND A NUMBER I NEARLY BLAMED ON THE WRONG THING
5ZZP called `daily_slices` on **every request** (3.24s of a 3.9s warm response).
  market view WARM  **3.9s -> 0.02-0.23s**   own cold 9.9s -> 11.0s
Cache keyed on **store MTIMES, not a clock** - *a TTL hands back a stale answer as a fresh one
until it expires.*
**First reading said "cold 95s"** and read as the new work making it worse. Measured properly:
**the FIRST request to a fresh backend costs ~62s WHICHEVER endpoint it is** - a cheap reader
took **62.63s** in that position; the market view took 11.0s once something else had paid it.
**That minute belongs to backend startup and predates all of this** - recorded as its own
finding rather than folded into a figure that would have made this stage look responsible.

### DASHBOARD
Setup-conditions cards under the chart (**only the NEAREST failure emphasised** - colour alone
makes four cards shout at once). Regime: full posterior as bars + uncertainty in bits + a
**"Why this label"** table (input · value · 60d pct + z · lean), `no lean` where none can be
claimed. Both **outside** the chart box -> **height spread 0px, 0 overflow at 375/720/1440**.

### INTENTIONALLY NOT EXPOSED
price line for Stress (setup is counts, not a price) · distance-to-entry for NKD/Swing
(publishing one means forming an entry the detector never formed) · Calm phase diagnostics
(DECIDE vs OBSERVE) · a regime threshold (Viterbi has none) · per-feature attribution.

### TESTS - 35 NEW
Metric values checked **against the detector's own output**, not re-derived. Entropy checked
**against its definition**, not the implementation. The page is scanned for
build_feature_matrix/predict_proba/Math.log/entry_conditions/peer_features/breadth_min.
**2 defects caught:** the feature table **overflowed 208px at 375px** (a scroll box would have
HIDDEN it, not removed it - rows now stack below 560px); and **a case-sensitivity slip of mine,
the THIRD in these panels** - three in three stages is a property of the page, not a slip.
  5ZZQ + 5ZZP + 5ZZL/M + dashboard backend + contract + DOM + ops + 5ZZO -> **423 passed, 0 failed**

### SAFETY
orders_possible **False -> False** · blocking unchanged · confirmation untouched · scheduler
untouched (pid 3000) · orders dir ABSENT · 0 broker calls · 3 backend restarts (read-only
dashboard only, via `restart --no-scheduler`).
RUNTIME WRITTEN: one appended regime-label record. **No trading file touched.**

### Files touched
NEW: scratch/test_track1_stage5zzq_setup_boundaries_hmm_explain_20260828.py,
     scratch/track1_stage5zzq_setup_boundaries_hmm_explain_20260828.{md,json}
MOD: global_index/track1_regime_record.py, monitor/backend/track1_market_view.py,
     global_index/dash/realtime/{realtime.js,realtime.css,index.html}, pipeline doc, TASK.md

---

## Task: Stage 5ZZP - "not published" was never the same as "not computed"
Status: DONE, scope stated (2026-08-28). **NO ORDERS.** approval unset · no --allow-orders ·
no orders dir · confirmation untouched · scheduler untouched · no broker call ·
**0 trading decisions moved (MEASURED)**. **414 passed, 0 failed.**

### THE FINDING
5ZZL read **RETURN TYPES** and concluded nothing was published under the verdicts. Reading the
**IMPLEMENTATIONS**:
  Stress rules  every value computed, compared to a named threshold, **then dropped**
  Regime score  `HMMEngine.predict_proba` exists - the posterior is **real**
  Volume        present in **EVERY** store, simply never aggregated
  Regime thresh **genuinely absent** - and now says WHY from the mechanism

### STRESS - the values were one frame below the slot that said it had none
`entry_conditions` made 4 comparisons -> bool. Values from `peer_features`, thresholds from
`StressParams`, **both at the call site** - only the JOIN was thrown away, while the slot above
wrote `not_exposed_by_sleeve` into its own record.
Two single-source refactors: `entry_checks()` states the comparisons AS DATA and
`entry_conditions` is now `all()` over it; `basket_state()` is the detector's own opening,
extracted. *One computation, two readers - not two computations with one answer each.*
**PROOF NOTHING MOVED:** entry_conditions **5,760 cases x 5 param sets -> 0 mismatch**;
detect_entry_for_slot **652 slot-days, 215 WITH REAL SETUPS -> 0 differences.**
*The 215 matters: the first 40-day sample was ALL-EMPTY and would have proved nothing. Widened
until it held 97 genuine setup days.*
**A no-signal slot now says (2026-08-27):** breadth 4/4 PASSES · gapped down **0 (needs 3)** ·
avg gap **+0.51% (needs <= -0.10%)**. A MARKET answer, not a data answer.

### REGIME - a real score, and no threshold at all
  predict_current -> `self._model.predict(X)[-1]`  **Viterbi decode**
  predict_proba   -> posterior per state
  **score 0.998354** (posterior of the labelled state) · **margin 0.996711 over Normal**
  states Calm .998354 / Normal .001643 / Stress .000003 · viterbi==argmax **8/8, flagged if not**
**NO THRESHOLD** - Viterbi compares states to EACH OTHER, never to a cut, so there is no line to
be near; a "distance to threshold" display would describe a procedure the model does not use.
The **lead over the runner-up** stands in its place, named a lead. A test reads engine.py so
that sentence cannot silently become false. Still RECORDED not computed per request (8.54s).

### VOLUME - it was there all along
MNQ every bar mean 3,195 · MES every bar mean 1,269 · MNKD 270/500 mean 2.5 (thin).
Summed per 5m bucket, pane drawn INSIDE the chart's existing box -> panel height unchanged.
`volume_status` has **4** values - a column of zeros and an absent column must not draw the same.
**Nothing synthesised**, and a test forbids it.

### SCOPE - what is NOT done, and why (named, not left looking finished)
- **NKD/Swing rule diagnostics**: detector returns `SwingSetup(entry,stop,daily_atr,regime)` on a
  setup and `None` otherwise. Entry+stop ARE published on signal days; on quiet days the entry
  comes from a per-bar signal fn, not a standing level. **Publishing a distance would mean
  forming an entry the detector never formed.** -> `not_computed_until_entry` + the reason.
- **Calm**: `entry_conditions` DOES return a dict, but the live path is the two-phase contract
  and DECIDE must not show OBSERVE's values (a 10:00 price on a 09:32 decision).
  **Left unwired rather than wired wrongly.**
- **Per-slot persistence**: belongs with the slot's write path = the decision path. Out of scope
  for a stage contracted to change no decision.

### A STATEMENT IN THE SOURCE THAT HAD BECOME FALSE
The regime module's docstring said the model published no score/probability - written from the
return type, and wrong. **Corrected where it lives**, engine calls quoted. **4 test assertions
defending the same defunct claim corrected with it** - correcting only the code would have left
the tests guarding the error.

### MY OWN MISREADINGS
Took `MES has no bars for this session` for a defect - it was **01:56 ET on the NEXT session**;
the diagnostic was right, my reading wrong (**the three-clock trap**). And a DOM assertion was
case-sensitive against a CSS-uppercased label - **the identical trap 5ZZM hit**.

### TESTS
22 new. Equivalence keeps the **PRE-refactor function in the test file** - comparing new code
against a re-reading of itself is true by construction.
  5ZZP + 5ZZL/M + dashboard backend + contract + DOM + ops + 5ZZN + 5ZZO -> **414 passed, 0 failed**

### SAFETY
orders_possible **False -> False** · blocking unchanged · confirmation untouched · scheduler
untouched (pid 3000, track1-only-shadow, 0 legacy entry jobs) · orders dir ABSENT · 0 broker calls
RUNTIME WRITTEN: one appended regime-label record. **No trading file touched.**

### Files touched
NEW: scratch/test_track1_stage5zzp_strategy_levels_regime_metrics_20260828.py,
     scratch/track1_stage5zzp_strategy_levels_regime_metrics_20260828.{md,json}
MOD: global_index/track1_stress_mnq.py, global_index/track1_regime_record.py,
     monitor/backend/track1_market_view.py, global_index/dash/realtime/{realtime.js,realtime.css},
     scratch/test_track1_stage5zzl_*.py, pipeline doc, TASK.md

---

## Task: Stage 5ZZO - a guard that fired where nothing was starting
Status: DONE (2026-08-27). **NO ORDERS.** approval unset · no --allow-orders · no orders dir ·
confirmation untouched · **scheduler untouched (pid 3000 -> 3000)** · no broker call.
**395 passed, 0 failed** - and the 5ZZJ alarm went GREEN on its own terms.

### ROOT CAUSE
5ZZN's guard ran **UNCONDITIONALLY**, before anything decided whether a scheduler was being
started. So `restart --no-scheduler` - *leave the scheduler alone, rebuild the backend* - was
refused with *"this start would register 45 legacy entry job(s)"*, about **a start nobody
requested**.
Worse than a wrong message: it was the **only** route to a backend restart, which 5ZZN had just
documented as the way to pick up the new API route. **A guard that fires where nothing starts is
not stricter - it teaches the operator to go around**, and the way around was
`restart --scheduler`: restarting a LIVE scheduler to rebuild a READ-ONLY backend. The
stricter-looking guard pointed at the more dangerous act - the same shape as the bug it had just
fixed, one command over.

### FIX - two start sites, not one
1. **explicit restart** - `if args.restart_scheduler and not track1_only:`, still checked
   BEFORE `ensure_single` stops anything (5ZZN's property kept).
2. **the cold-start path in the `else` branch** - easy to miss and matters more: when NO
   scheduler is running, the branch meant to *leave one alone* **starts one**, in legacy mode,
   with no Track 1 flag on the call. Both `up` and `restart --no-scheduler` reach it. So a
   backend-only restart with nothing running is a REAL legacy start and is still refused.
**Nothing relaxed** - the guard covers exactly the same set of real starts.

### MATRIX (stubbed world; every refusal touched NOTHING)
  restart --no-scheduler        sched running -> **allowed**, backend only
  restart --no-scheduler        none running  -> refused (cold start would be legacy)
  restart --scheduler default   -> refused, nothing stopped
  restart --scheduler --track1-shadow -> refused (keeps all 45)
  restart --scheduler --track1-only-shadow -> **allowed**
  up  running -> allowed, leaves scheduler alone | up  none -> refused

### LIVE VERIFICATION
  BEFORE sched=[3000] backend=[38152]  ->  AFTER sched=**[3000]** backend=**[28320]**
  `scheduler=UNTOUCHED - pid 3000 ... (8m ago)` · mode still **compatible**, legacy_entry_jobs=0
  slot_table=fresh · blocking=['PAPER_SHADOW_EVIDENCE'] · orders_possible=False
**THE 5ZZL ROUTE IS NOW SERVED.** First request timed out at 25s - stated precisely: that was
the **cold import chain on a freshly started backend, not the endpoint**. Measured right after:
**1.47s cold / 0.11s warm**. The day-slice cache is doing its job.

### TESTS - 15 NEW
The regression is asserted **twice**: on the output, and **at the guard itself** (a spy on
`legacy_entry_start_blockers` proving a backend-only restart never consults it) - *a message
that stopped printing for some unrelated reason would pass a text check and prove nothing.*
What must stay refused is pinned, including **the case the fix must not open**:
`restart --no-scheduler` when there is no scheduler to leave alone.
**1 x 5ZZN test restated**: it pinned the literal source line `if not track1_only:` which this
stage rewrote. *A source pin goes stale the first time the code around it moves.* Behavioural now.
  5ZZO + 5ZZN + 5ZZ + test_ops + dashboard backend + 5ZZJ + 5ZZK + 5ZQ + 5ZR -> **395 passed, 0 failed**
**The 5ZZJ alarm PASSES** - and for the right reason: the scheduler is genuinely in
track1-only-shadow with 0 legacy entry jobs. It was left red at the end of 5ZZN precisely so it
would only go green when that became true.

### SAFETY
orders_possible **False -> False** · blocking unchanged · confirmation True untouched ·
scheduler pid unchanged · approval unset · orders dir ABSENT · 0 broker calls
Both commands now behave as documented:
  `python monitor\ops.py restart --no-scheduler --yes`                    (backend only)
  `python monitor\ops.py restart --scheduler --track1-only-shadow --yes`  (compatible mode)

### ONE THING I COULD NOT EXPLAIN
The backend started during verification (28320) served normally - incl. the new route, 200 -
until 23:04:53, then **exited with nothing recorded**. Ruled out by measurement: no traceback in
either log stream · **no kill entry in ops.log** · it detaches with the same flags as the
scheduler so it was not orphaned by my shell. **Cause UNKNOWN - not guessed at.** Restarted with
the same command (pid 46600), dashboard up. If it recurs, capture whether it coincides with the
market-view route's cold parquet read - the only new work this backend does.

### Files touched
NEW: scratch/test_track1_stage5zzo_backend_restart_guard_20260827.py,
     scratch/track1_stage5zzo_backend_restart_guard_20260827.{md,json}
MOD: monitor/ops.py, scratch/test_track1_stage5zzn_*.py (one source pin -> behavioural),
     pipeline doc, TASK.md
RUNTIME TRADING FILES WRITTEN: **none**

---

## Task: Stage 5ZZN - the guard that pushed the operator into the unsafe mode
Status: DONE in code (2026-08-27). **NO ORDERS.** approval unset · no --allow-orders · no orders
dir · confirmation untouched · **scheduler NOT restarted** · no broker call · no strategy/slot/
threshold/SEND-wire/evidence change.
**ONE TEST LEFT RED ON PURPOSE** - see Part E command.

### ROOT CAUSE
`ops.track1_shadow_blockers` refused a Track 1 shadow start **because the confirmation FILE
EXISTS**, with the reason *"that file arms the Track 1 route."* True when written - the
signature was then the only thing between this route and an order. **Stage 5S** added a measured
evidence gate and **5ZZK** gave B1 a measured half; neither came back to this guard.
  operator signs B1            -> confirmation exists
  --track1-only-shadow REFUSES -> because of that file
  scheduler restarted, no flag -> **45 legacy entry jobs on the login just declared retired**
**The guard pushed the operator OUT of the only safe mode and INTO the unsafe one.**
Not a missing check - **a check whose premise had expired, still enforcing, pointing the wrong way.**

### PART A - MEASURED BEFORE EDITING
  pid 11332, started 21:51:23, argv `run_scheduler --port 4002 --shadow-resume` (no T1 flag)
  legacy entry **45 registered** · Track 1 slots **0** · confirmation True · orders_possible False
  **VERIFIED not assumed**: an earlier probe printed the command line one char per line, which
  would have meant the mode reading was type-confused and the alarm a FALSE POSITIVE. It is not.
  job counts:  legacy/default 45/0 · --track1-shadow 45/71 · --track1-only-shadow **0/71**
**2nd DEFECT FOUND**: status said `track1_slot_table=fresh registered_slots=71` - a statement
about a process that had **already exited** (last registration 05:08:33, running proc 21:51:23,
registered none). *A freshness check against a dead process's log reports on the wrong system
with full confidence.*

### PART B - CHOSE **OPTION A** (relax the guard, invent no mode)
The guard now asks the **gate registry** whether an order is actually possible - since 5ZZK it
reads the file AND every blocker's measurement. Half of the old guard KEPT: if every blocker is
clear, a shadow start really is starting something nobody asked for. **Fails CLOSED** - an
unreadable registry reads as "possible" so the guard refuses rather than waving through.
*Why no new mode:* --track1-only-shadow already registers 0 legacy entry jobs, keeps legacy
safety draining, and cannot send. A new name = one more thing to explain and keep in step.

### PART C - THE GUARD THAT NEVER EXISTED
`legacy_entry_start_blockers()` refuses a start that would register legacy ENTRY jobs against a
signed decision, naming 4 things (what B1 says · what this start would do · use
--track1-only-shadow · or retire the decision first).
**Refuses BEFORE anything is stopped** - restart kills first, and a guard firing after that
leaves the operator with no scheduler. Proven: ensure_single/stop_runners/start_scheduler all
untouched, rc=2. **--track1-shadow is NOT exempt** (keeps all 45). One table, three readers.

### PART D - STATUS
  `track1_scheduler_mode=INCOMPATIBLE confirmation=True legacy_entry_jobs=45`
  `MODE CONFLICT - ...` + `fix: python monitor/ops.py restart --scheduler --track1-only-shadow --yes`
Three states incl. **unknown** - a mode nobody could read is NOT compatible.
2 stale sentences repaired: `slot_table` -> **stale_log**; and `orders: impossible - B1 open and
no confirmation file` (**false on BOTH halves** after signing, still printing) -> now asks the
registry: `impossible - blocked by PAPER_SHADOW_EVIDENCE`.

### PART E - THE COMMAND (verified accepted, NOT RUN)
  `python monitor\ops.py restart --scheduler --track1-only-shadow --yes`
`track1_shadow_blockers(track1_only=True)` returns `[]` against the REAL signed confirmation.
After it: conflict clears, slot_table returns fresh, **the 5ZZJ alarm passes BECAUSE the mode is
compatible** - not because anything was loosened. Orders stay impossible either way.

### PART F - BACKEND, KEPT SEPARATE
5ZZM polish is source-only; the 5ZZL route still needs a backend restart:
  `python monitor\ops.py restart --no-scheduler --yes`  (leaves the scheduler alone) - NOT RUN.

### TESTS - 26 NEW, ALL 10 ITEMS
0 processes started/stopped, production confirmation never touched.
**The 5ZZJ alarm is PINNED AS STRICT** - a test reads that file and asserts
`capability != dec.LEGACY_ENTRY_PRESENT` is still there and has not become a skip.
**3 of my own mistakes, all caught by RUNNING:** compared scheduler job ids vs slot-table ids
(lowercase vs upper) · a test Namespace missing `api_port` · **`slot_table_freshness` scanned the
LIVE process table inside itself**, so 5ZZ unit tests handing it a fixture failed because the real
scheduler outside started later - *a function that reads ambient state cannot be asked a
hypothetical*; the process start is passed in now.
  5ZZN + 5ZZ + test_ops + dashboard backend + 5ZZK + 5ZR + 5ZQ + 5ZZJ -> **379 passed, 1 failed**
  The 1 = **the 5ZZJ alarm, still red because the PROCESS has not been restarted.** Correct state.
  **4 ops tests ISOLATED, not weakened** - they describe a legacy start and were reading the real
  machine's confirmation; now pointed at a nonexistent path (the pre-B1 world they were written
  for), and the refusal they would have hit is asserted in the 5ZZN suite.

### SAFETY
orders_possible **False -> False** · blocking ['PAPER_SHADOW_EVIDENCE'] unchanged · confirmation
True untouched · B1 closed -> closed · approval unset · orders dir ABSENT · 0 broker calls
EXTERNAL: scheduler pid 11332 started 21:51:23 with no Track 1 flag - the restart that caused
this, done outside these stages.

### Files touched
NEW: scratch/test_track1_stage5zzn_scheduler_mode_enforcement_20260827.py,
     scratch/track1_stage5zzn_scheduler_mode_enforcement_20260827.{md,json}
MOD: monitor/ops.py, monitor/test_dashboard_backend.py (stub isolated),
     scratch/test_track1_stage5zz_*.py (one stub signature), pipeline doc, TASK.md
RUNTIME TRADING FILES WRITTEN: **none**

---

## Task: Stage 5ZZM - Market View / Regime Monitor visual polish
Status: DONE (2026-08-27). **NO ORDERS.** approval unset · no --allow-orders · no orders dir ·
confirmation untouched · **scheduler NOT restarted by me** · no broker call · no strategy/
threshold/window/schedule/gate change.

### *** READ FIRST - EXTERNAL CHANGE THAT OUTRANKS THIS STAGE ***
A 5ZZJ test went RED during regression. **It is not a test problem - it is the alarm working.**
  scheduler pid      14344 -> **11332**            restarted EXTERNALLY, not by me
  track1_mode        track1-only-shadow -> **legacy-only**
  legacy entry jobs  not registered -> **REGISTERED**
  B1 gate            **still closed** · orders_possible **False**
The B1 decision signed 2026-08-27 asserts *legacy is retired FOR THIS PAPER LOGIN*. The running
scheduler now registers legacy entry jobs on that same login, and the gate goes on reading the
recorded decision as true. **This is verbatim what the 5ZZJ preview warned:** *"legacy is
dormant because of a command-line flag, not because it has been retired; a restart without
--track1-only-shadow registers its entry jobs again."*
Nothing unsafe can execute (PAPER_SHADOW_EVIDENCE holds, approval unset, no order path armed).
**TEST LEFT RED ON PURPOSE** - it is the only thing that notices this; making it pass would
remove the alarm and leave the condition. **Needs an operator decision.**

### BEFORE -> AFTER (browser-measured, 375/720/1440)
  page overflow      0/0/0        ->  0/0/0
  container overflow 0            ->  **0 on all six containers, all widths**
  chart height/tab   spread 0.0px ->  spread **0.0px**
  chips in summary   **0**        ->  **5**
  legends            **0**        ->  **2** (markers + regime)
  raw phrase visible **yes**      ->  **none**
  footer             duplicated the summary  ->  **empty**

### WHAT CHANGED VISUALLY
- summary -> **chips in the page's OWN idiom** (3px 6px, 1px currentColor, radius 3, 700/11
  mono, uppercase) - the shape `.issue-status`/`.issue-origin` already wear. No 2nd language.
- chart padding left **8px -> 34px** (candles were running into the border)
- slot markers lifted off the plot floor onto **their own baseline** above the time axis -
  the difference between a row of outcomes and stray ink
- candle width 1.5-11px -> **2.5-9px** (readable at 1440, distinct at 375)
- window band labelled `Window` **only when wide enough** not to sit on a candle
- marker key laid **OVER** the chart's fixed box, not below it -> height unchanged
- regime label is now the **anchor** (22px, coloured), never shown without its date + age
- 60-day run **quieter** (10px, 80% opacity) + colour legend + recent days spelled out

### COPY
  `entry levels not exposed by sleeve evidence yet` -> **`Strategy levels unavailable`** + tooltip
  `splice_result`->`Data join` · `not_exposed_by_sleeve`->`Not published`
  `provider_lag`->`Data delayed` · `gate_refused`->`Gate refused`
  `PASS - 1761 compared, none changed` -> **`Label check passed - 1,761 days compared - no drift`**
  `not exposed by model` -> **`Score not published` / `Shift threshold not published`**
  `NO BARS TO SHOW` -> **`No bars available for this session`** + latest stored session
Translation lives in ONE place. An **unmapped** token is shown with underscores removed, not
folded into "unknown" - a phrase nobody has translated should be visible so somebody does.

### STILL UNAVAILABLE (nothing publishes it)
entry/stop/target/reference price · regime score · shift threshold · distance-to-shift ·
today's bars (not persisted until the daily append). **No distance-to-shift implied anywhere**,
and a test asserts it.

### THREE FAULTS I INTRODUCED, MEASURED BACK OUT
- regime panel **overflowed 178px @720 / 111px @1440**: the new anchor is a grid child, and a
  grid child without `min-width:0` refuses to shrink below its content
- **two tooltips pushed panels sideways** (11px regime grid, 85px chip row). The page already
  solves this for header zones - same flip reused, no second remedy invented.
  *The 85px one appeared **ONLY AFTER** the shorter copy let chips reflow onto fewer lines -
  this overflow moves when the text moves, which is why 3 widths are measured after EVERY copy
  change, not once.*
- **the DOM fixture had the OLD phrase typed into it**, so the probe reported the old wording as
  still visible after the backend stopped emitting it. It reads the constant now.

### TESTS
**73** in the market-view suite (**26 new**). 6 x 5ZZL copy pins **restated, none weakened** -
each keeps its invariant (levels still SAID · refusal still FINDABLE via chip+tooltip · empty
state still intentional · absent score still NAMED).
  dashboard backend + contract + DOM + ops + 5ZZL/M + 5ZZH + 5ZZK + 5ZZJ
  -> **440 passed, 1 failed** = the external scheduler-mode change above. Nothing else red.

### SAFETY
orders_possible **False -> False** · blocking ['PAPER_SHADOW_EVIDENCE'] unchanged ·
confirmation True untouched · approval unset · orders dir ABSENT · 0 broker calls
**BACKEND RESTART still needed** for `/api/v1/track1-market-view` (unchanged since 5ZZL; this
stage's copy rides along): `python monitor\ops.py restart --backend` - NOT RUN.

### Files touched
NEW: scratch/track1_stage5zzm_market_view_visual_polish_20260827.{md,json}
MOD: monitor/backend/track1_market_view.py (copy only),
     global_index/dash/realtime/{realtime.js,realtime.css},
     scratch/test_track1_stage5zzl_market_view_regime_20260827.py, pipeline doc, TASK.md
RUNTIME TRADING FILES WRITTEN: **none**

---

## Task: Stage 5ZZL - Track 1 Market View + Regime Monitor
Status: DONE (2026-08-27). **NO ORDERS.** approval unset · no --allow-orders · no orders dir ·
confirmation untouched · scheduler NOT restarted · **no broker call** · no strategy/threshold/
slot/gate/SEND-wire change.

### TWO FINDINGS THE PANEL HAD TO BE BUILT AROUND
1. **TODAY'S BARS ARE NOT PERSISTED ANYWHERE.**
     MNKD last 2026-08-26 17:45 · MNQ 17:44 · MES 17:44 · **rows for 2026-08-27: 0**
   The store is appended once a day; the live half is spliced **in memory** in the slot process
   and thrown away. The overnight sleeve used **1,910** of today's bars and none survives.
   -> each sleeve draws the most recent STORED session and **says which**. Substituting it
   silently would make a stale chart look current.
2. **NOTHING PUBLISHES A PRICE, AND THE MODEL PUBLISHES NO SCORE.**
   Every rule: `source=not_exposed_by_sleeve, value=null`. `label_regimes` returns strings.
   -> `entry levels not exposed by sleeve evidence yet` / `not exposed by model`, in words.
   *A line drawn at a level nobody published is a line an operator would trade against.*

### PART C - LIGHTWEIGHT CHARTS **NOT** ADDED (measured first)
  package.json / node_modules / build step: **NONE** · realtime page scripts: **2, both ours**
  only `chart-forward.html` uses a CDN - and its consumer guards `if (!window.Chart) return`
De-facto no-external-dependency policy on the operator page. **Tradeoff stated:** a CDN tag on
THIS page makes a third-party host a dependency exactly when something is going wrong; vendoring
commits a blob into a repo that has none - the owner's call, not a stage's. -> **first-party
SVG**, same idiom as shared/live.js. Cost: ~200 lines (crosshair/tooltip/scale/axis) a library
would have given. Payload already matches what Lightweight Charts consumes; swap is small.

### REGIME IS RECORDED, NOT COMPUTED ON REQUEST
`label_regimes` = **8.54 SECONDS**. An endpoint calling it would hang the page after every SPY
refresh and on every cold backend. New probe `global_index/track1_regime_record.py` - same shape
as track1_b1 / account_baseline / regime_verify. **Fails to UNKNOWN, never to a label** (Calm is
the permissive regime). Record carries the **fit window** - a label without it is a label nobody
can reproduce (the FreezeRecord mistake, again).

### NEW ENDPOINT `/api/v1/track1-market-view`
Its own endpoint - it slices instrument stores; /track1-runtime is polled short-interval.
  bars   parquet day-slice -> 5m -> clipped to context range, cached by (path, mtime, day)
  slots  signal rows + slot table, so unfired slots are **future** not missing
  levels scanned from rule_checks where source==measured - **empty today**, written as a scan so
         a future published price appears without anyone editing the file
  data   the observation row incl. the `provider_error` 5ZZI wired in
LIVE: NKD complete 38 bars 22 no_signal · Stress incomplete 39 bars 18 no_signal + 6 refused ·
Swing waiting 80 bars 22 future. Calm excluded (one-shot contract, no window to draw).

### LIVE CORRECTION TO 5ZZI
5ZZI recorded every fetch from 03:05 ET returning zero. The 12:30 Stress row now reads
`live_rows_fetched=2490, splice_result=ok` - **the feed RECOVERED during the Stress window.**
The outage was bounded, not ongoing.

### FOUR DEFECTS MEASUREMENT CAUGHT (reading would not have)
- **two definitions of "observed"**: the summary counted markers -> `24/24` for a sleeve the
  ledger recorded as **18/24** (a refused slot leaves a row here, is not an observation there).
  The ledger owns the count now; markers only draw.
- **"Data refused" over a working feed**: any provider_reason read as a refusal, so Swing - not
  yet open - was painted as a data problem. `ok is None` = nobody looked.
- **the regime panel rendered UNSTYLED**: fact CSS was scoped `#track1Facts` only -> label
  `inline` 14px instead of `block` 11px -> **"RegimeCalm as of 2026-08-26"** on the page. Caught
  by comparing COMPUTED STYLES against the Track 1 panel, not by looking.
- **the render calls landed in the ISSUE-ROW CLICK HANDLER**, not the render pipeline - the whole
  feature only appeared after clicking an issue. Found by DOM tests timing out on tabs that were
  never drawn; a code-read would have shown the call and looked correct.

### LAYOUT, MEASURED IN A BROWSER
                 page overflow   chart      chart height per tab
   375px             0px         343x240    [240,240,240]
   720px             0px         668x240    [240,240,240]
  1440px             0px         935x320    [320,320,320]
Tab switch and empty state both leave the panel height unchanged.
Regime row now reads `REGIME | Calm as of 2026-08-26 · read 0.3h ago | LABEL CHECK | PASS ...`

### FRONTEND COMPUTES NOTHING - ASSERTED, NOT CLAIMED
Scanned for label_regimes/benchmark_daily/decode(/atr(/stdev(/Math.exp/Math.log/level arithmetic
- **scoped to the added block**, because the page has long-standing PROSE naming the model ("The
HMM stale guard is hard-tripped") and a whole-file search fails on a label. That is exactly how
my first version of that test failed. Timestamps split as STRINGS, never `new Date` - they are
wall-clock on the sleeve's exchange clock (the thirteen-hour error class, again).

### TESTS - 47 NEW
3 of my own test bugs: whole-file `HMM` search hit prose · NKD fixture made 09:30 bars for a
01:10-02:55 window so no bar hit the band · assertion pinned to casing CSS uppercases.
Registrations the existing tests DEMANDED: new endpoint into the realtime contract, and into the
shared DOM fixture (an unstubbed route = console 404 = healthy-page test fails). Contract
list-slot pinned `sleeves`, a **dict** - caught instantly, repointed at regime.recent/context.
1 restated: 5ZZH's blocker test pinned B1, which **5ZZK closed**.

### SAFETY
  orders_possible **False -> False** · blocking ['PAPER_SHADOW_EVIDENCE'] unchanged
  confirmation True, untouched · approval unset · orders dir ABSENT · 0 restarts · 0 broker calls
**BACKEND RESTART REQUIRED** for the new route (`python monitor\ops.py restart --backend`) -
NOT RUN. The page handles its absence: the fetch is independent and a failure leaves every other
panel as it was. Scheduler must NOT be restarted and was not.
RUNTIME WRITTEN BY THIS STAGE: `track1_runtime/regime_label/regime_label_20260827.jsonl` (new
evidence dir, the regime probe). **No trading file touched.**

### Files touched
NEW: global_index/track1_regime_record.py, monitor/backend/track1_market_view.py,
     scratch/test_track1_stage5zzl_market_view_regime_20260827.py,
     scratch/track1_stage5zzl_market_view_regime_monitor_20260827.{md,json}
MOD: monitor/backend/app.py (endpoint), global_index/dash/realtime/{index.html,realtime.js,
     realtime.css}, monitor/test_realtime_contract.py, monitor/test_realtime_dom.py,
     scratch/test_track1_stage5zzh_*.py, pipeline doc, TASK.md

---

## Task: Stage 5ZZK - the gate could not see the decision  ** B1 IS NOW CLOSED **
Status: DONE (2026-08-27). **NO ORDERS.** approval unset · no --allow-orders · no orders dir ·
scheduler NOT restarted · **no broker connection** · no runtime trading file edited.

### ROOT CAUSE, ONE LINE
**`blocking()` defaulted to `NO_CONFIRMATIONS`**, so with no argument it answered a question
nobody was asking: *what would still block if the operator had signed nothing?*
NOT a schema mismatch, NOT stale evidence, NOT a hidden predicate inside B1. The file was valid,
parsed correctly, and released the gate the moment it was actually passed - and almost nothing
passed it.
  `blocking(conf)` -> ['PAPER_SHADOW_EVIDENCE']            correct
  `blocking()`     -> ['B1_...', 'PAPER_SHADOW_EVIDENCE']  what everyone saw
**Callers passing confirmations: 1 of 7** - only `run_live_day_track1.py:181`. The status
command, readiness report, dashboard, ledger and **order executor** were all blind.
Family: **a default standing in for a real answer** - 4th occurrence in this project. It failed
CLOSED so nothing unsafe followed, but **a gate that cannot be seen to open is a gate nobody can
finish.**

### THE FIX, AND THE STRENGTHENING THAT CAME WITH IT
1. `blocking(conf=None)` -> reads the signed file. Unreadable/half-parsed grants **nothing**.
   Unsigned view still available as `blocking(NO_CONFIRMATIONS)`; the preview now asks by name.
2. B1's required measurement widened `legacy_broker_flat` -> **`b1_decision_evidence`**:
     B1 audit PASS · **book route stamp** · **account baseline PASS** · account named/matching
   **Strictly stronger** - nothing that was required stopped being required. The route stamp and
   the baseline had NEVER been checked.
3. Preview baselines against NOTHING SIGNED - otherwise, with a decision in place, it compared
   the signed state against itself and said the candidate would release nothing.
**CONFIRMATION SCHEMA UNCHANGED. The operator did not have to re-sign.**

### A CHECK THAT COULD NEVER HAVE FAILED (caught before shipping)
v1 of the widened measurement took route + account_id **from the audit record. Neither is
recorded there.** Both clauses were `if value and value != expected` -> skipped every time,
appearing in the reasons list exactly like a check that passed.
Caught by **printing the detail and noticing two clauses produced no words.** Route now read
from the book file the audit names; missing stamp = refusal.
One clause genuinely cannot run (the audit records no account id) and is printed as
**"NOT CHECKED"**, not counted as a pass.

### PART D - VERIFIED
  confirmation=True · **track1_blocking=['PAPER_SHADOW_EVIDENCE']** · orders_possible=False
  track1_orders_approved=False · orders dir ABSENT · b1 PASS, all books 0
Every expected value, exactly.

### TESTS - 27 NEW, ALL 11 ITEMS
Canonical fixture = the operator's REAL file, with a test asserting it still matches. Item 11
**shown not claimed**: the preview parses via `gates.load_confirmations` and is asserted never
to parse the confirmation itself.
**THREE BUGS IN MY OWN FIX, ALL FOUND BY TESTS:**
- `path = CONFIRMATION_PATH` **bound at DEFINITION time** -> patching the constant changed
  nothing while appearing to; 3 refusal tests were reading the **production file** and passing
  for the wrong reason. **Identical trap to 5ZZE's MAX_RECORD_AGE_HOURS, two days earlier.**
- a test **read prose instead of behaviour**: searched the source for TRACK1_ORDERS_APPROVED,
  which appears in the registry's own text describing that variable. Now behavioural.
- a blanket string replace **rewrote my new helper into a call to itself** -> RecursionError.
**10 SEAMS REPOINTED** (5ZR + 5ZQ, plus the whole 5ZZJ fixture): widening the measurement meant
`setitem(MEASUREMENTS,"legacy_broker_flat",...)` no longer reached the gate - the patch sat
there while the gate walked past it to the real evidence. Without this, **5 tests named "a
decision without a usable measurement still blocks" would have gone on passing for reasons they
had not chosen.** Second time in three stages a rename left a suite green and hollow.
**5 RESTATED, NOT WEAKENED** - the operator signed and B1 genuinely closed:
  5ZR23 no file exists -> *this stage* made none; if one exists it must validate
  5ZR24 orders impossible AND B1 blocks -> orders impossible, and the evidence gate is why
  5ZQ32 ledger publishes legacy_broker_flat -> publishes the composite, and the name resolves
  5ZQ35 orders impossible + no file -> that never depended on the file's absence
  5ZQ36 **"B1 still blocks today" -> "B1 is closed, and NEVER by a signature alone"** - remove
        the measurement and it returns. **Better than the test it replaced.**
  Suites: 5ZZK+5ZZJ+5ZR+5ZQ+ops+ops-status+dashboard backend+realtime contract  **379 passed**
  **Pre-existing failures: 0.**
**MUTATIONS 8/8 RED.** One was GREEN on the first run - and NOT because a test was asleep: it
rewrote the body of an `except` that **never fires** (`load_confirmations` answers bad JSON by
returning nothing-granted rather than raising), so it mutated **unreachable** code. *An
unreachable guard is worse than a sleeping one: it looks like a safety net and a real failure
finds nothing underneath it.* Fixed not by retargeting the mutation but by **making the guard
reachable** - a test forces the loader itself to raise. The original mutation then turns red.

### SAFETY - BEFORE AND AFTER
  orders dir ABSENT · TRACK1_ORDERS_APPROVED unset (**and setting it moves no blocker - tested**)
  --allow-orders absent from scheduler/ops · 0 restarts · 0 broker connections
  orders_possible **False -> False** · B1 NOT weakened
Reading a confirmation makes a decision **VISIBLE**. It cannot make it **SUFFICIENT**: orders
also need the approval env, --allow-orders, and PAPER_SHADOW_EVIDENCE, which is measured and
cannot be signed for.

### WHERE THE ROUTE STANDS
**One gate left.** The account question is settled - by a decision AND by evidence that has to
keep passing. Orders remain impossible, held by the only thing that should hold them: whether
the shadow record is good enough to justify one.

### Files touched
NEW: scratch/test_track1_stage5zzk_b1_confirmation_recognition_20260827.py,
     scratch/track1_stage5zzk_b1_confirmation_recognition_20260827.{md,json}
MOD: global_index/track1_gates.py (default reads the file; ROUTE constant;
     b1_decision_evidence; ledger note), global_index/track1_b1_decision.py (preview baseline),
     scratch/test_track1_stage5zr_*.py, scratch/test_track1_stage5zq_*.py,
     scratch/test_track1_stage5zzj_*.py, pipeline doc, TASK.md
RUNTIME WRITES BY THIS STAGE: **none**

---

## Task: Stage 5ZZJ - B1 operator decision: measured, previewed, NOT YET SIGNED
Status: **BLOCKED ON OPERATOR** (2026-08-27). Parts A, B, E, F DONE. Part C refused by the
harness. **NO ORDERS.** No orders dir, no order journal, no --allow-orders, no scheduler
restart, legacy books read-only. One read-only IBKR connection, **client id 97**, announced first.

### TWO THINGS I NEED FROM THE OPERATOR
1. **May I place the decision file?** The harness auto-mode classifier refused it. It opens a
   go-live gate, so I did NOT reach for another tool to put the same bytes in the same place.
     `copy scratch\track1_b1_decision_candidate_20260827.json track1_go_live_confirmation.json`
   Those are the EXACT previewed bytes - anything else means the preview described another file.
2. **Was Part D.3 "confirmation remains false" meant literally?** Part C says write the decision;
   Part D.3 says confirmation stays false. **Measured: they are the SAME FILE** -
   `ops.TRACK1_CONFIRMATION` and `gates.CONFIRMATION_PATH` both resolve to
   `D:\raits\track1_go_live_confirmation.json`. Writing it NECESSARILY sets confirmation=True.
   I read D.3 as carried over from stages where the file was forbidden; the invariant that
   matters (**orders_possible=False**) holds either way and the preview proved it. If D.3 was
   literal, the decision cannot be recorded at all.

### PART A - THE MEASUREMENT WAS STALE, SO IT WAS REFRESHED FIRST
ops opened with `b1_legacy_flat=UNKNOWN (record_stale)` - "too old to count". Part A.5 applied.
  `python -m global_index.b1_audit --broker ibkr --record`  (client id 97, read-only)
  legacy book 0 · track1 book 0 · broker positions 0 · working orders 0 · equity 250,819.13
  **B1 PASS (legacy_and_broker_flat)** -> global_index/track1_b1/track1_b1_20260827.jsonl
  audit    checked 16:04:17Z  age 0.07h  expires 2026-08-28T16:04:17Z
  baseline checked 11:29:47Z  age 4.58h  policy max 24h  PASS USD 250,817.91 DUR125337
  track1 book **schema_version 2**, route **track1_candidate**, 0 positions
  confirmation ABSENT · orders dir ABSENT · orders_possible **False**
EXTERNAL: backend pid moved 6420 -> 45676 between 5ZZH and this stage. Not mine.

### PART B - PREVIEW (5ZR tool, candidate in scratch, production path untouched)
  validates yes · decision `legacy_retired_confirmed` · waiver not set
  measurement PASS, counts until 2026-08-28T16:04:17Z
  **legacy entries: none** -> Part B.3 stop condition NOT triggered
  would release **B1** · would still block **PAPER_SHADOW_EVIDENCE** · orders possible **False**
THE ONE WARNING, and it matters:
  *"Legacy is DORMANT because of a command-line flag, not because it has been retired: a restart
  without --track1-only-shadow registers its entry jobs again, and this recorded decision would
  go on reading as true."*
  Measured: **track1-only-shadow = 0 legacy strategy jobs; default mode = 45.** One flag apart.
  Does not block the decision (operator's call, already made) but it is the thing to carry
  forward - and it is why the running mode is now **pinned by a test**. Proper retirement is the
  switch-over runbook's ordered procedure, not this flag.

### PART D - ESTABLISHED BY PREVIEW AGAINST THE REAL REGISTRY, NOT OBSERVED ON DISK
  before [B1, PAPER_SHADOW_EVIDENCE] -> after [PAPER_SHADOW_EVIDENCE]
  orders_possible False · approved False · orders dir ABSENT · confirmation True (necessarily)
Refusal causes each separately tested: missing decision · stale measurement · FAIL/UNKNOWN ·
file that does not validate · unknown key · both decisions at once · waiver with no reason.

### PART E - B1 NOW APPEARS ON THE PAGE
It was in `ops status` and **nowhere on the dashboard**, so the operator had to leave the page to
learn whether the route's most consequential gate was open. Added `track1_runtime_reader._b1`:
decision + who/when, measurement status + age + expiry, broker/book counts, equity, blockers, one
operator line. **Three states**: `not_recorded` (normal, not an error) / `accepted` / `invalid` -
because invalid grants what absent grants (nothing) and means something completely different to
whoever fixes it. **`closed` is asked of the REGISTRY**, never computed from the two halves.
Legacy issues still scoped legacy, nothing deleted. Running backend will not serve the new block
until restarted (5ZZH's cached-module finding): `python monitor\ops.py restart --backend` NOT RUN.

### PART F - 26 TESTS, 9/9 MUTATIONS RED
**Wording correction**: 4 stage items say "cannot WRITE the decision without X". **There is no
writer** - `track1_b1_decision` writes nothing, deliberately: *"the confirmation file is written
by a person, never by a script, and that includes this one."* Honest translation, and what is
asserted: the decision does not **OPEN THE GATE** without X. Plus a test that the preview never
grows a writer.
**HARNESS DEFECT FOUND**: two mutations first returned **"GREEN - the guard is asleep" at exit 2**.
Exit 2 is a pytest USAGE error - my mutation broke the syntax and **nothing ran**. That label is
the worst available: a sleeping guard where there was no run. Same family as counting "nothing
collected" as a pass (third time). Harness now names exit 2-5 **"BROKE THE FILE - proves nothing"**.
**MY OWN TEST BUG**: the read-only proof built its candidate AFTER installing the write barrier, so
the test's own fixture tripped the trap and blamed the preview. Green would have proved nothing.
**2 STALE PINS REPAIRED** (5ZR): both froze `REGIME_LABEL_VERIFICATION` as blocking; its own
measurement released it 2026-08-26, so they failed for a reason with nothing to do with B1.
Roster-pin anti-pattern. Now the property: the preview reports everything blocking **except B1**.
  5ZZJ + 5ZR + 5ZQ + ops + ops-status + dashboard backend + realtime contract  **352 passed**
  Pre-existing failures: **2** (the stale pins) - repaired, not left red. Nothing else red.

### FINAL NUMBERS
  account DUR125337 · USD · baseline 250,817.91 · at audit 250,819.13
  broker positions 0 · working orders 0 · legacy book 0 · track1 book 0
  decision file `track1_go_live_confirmation.json` - **ABSENT**
  **B1 closed: NO** · **orders still impossible: YES**

### Files touched
NEW: scratch/test_track1_stage5zzj_b1_operator_decision_20260827.py,
     scratch/track1_b1_decision_candidate_20260827.json,
     scratch/track1_stage5zzj_b1_operator_decision_20260827.{md,json}
MOD: monitor/backend/track1_runtime_reader.py (the b1 block),
     scratch/test_track1_stage5zr_b1_decision_20260826.py (2 stale pins), pipeline doc, TASK.md
NEW RUNTIME EVIDENCE: global_index/track1_b1/track1_b1_20260827.jsonl (the refreshed audit -
     written by b1_audit --record, which Part A.2 instructed)

---

## Task: Stage 5ZZH - the biggest number on the page belonged to a different route
Status: DONE (2026-08-27). **NO ORDERS.** No confirmation file, TRACK1_ORDERS_APPROVED never
set, no orders dir, **nothing restarted**, no trading file written. Read-only API calls only.

### VERDICTS
  dashboard_account_source  LEGACY -> **TRACK1_BASELINE**
  open_issue_scope          SCOPED_NOT_GROUPED -> **GROUPED** (route_scope already existed from 5ZZF)
  track1_runtime_panel      silent about its blocker source -> **names it**
  orders_possible           **False -> False** (asserted before and after)

### FILE CORRECTION
The stage names `monitor/static/dashboard.{js,css}`. **Neither exists**, nor does
`monitor/static/`. The live dashboard is `global_index/dash/realtime/realtime.{js,css}`.

### WHAT THE CARD WAS SAYING
  `$50,408  +408  +0.82% since Aug 10  / base $50,000`
Every figure legacy: equity from a snapshot dated **2026-08-24**, base from its own
`meta.account`. The account this route would open from - **USD 250,818, proven flat against the
broker that morning** - was the small print underneath. 5ZZF fixed the small print and never
touched the headline, and the headline is what anybody sees first.

### THE RULE NOW, DECIDED IN THE READER NOT THE TEMPLATE
  usable          -> headline **USD 250,818**, currency in words; sub `baseline PASS - read 3.7h ago / USD 250,000`
  UNKNOWN / FAIL  -> **says which, and STOPS**
  no t1 block     -> the legacy card, unchanged
The refusal branch IS the point: reaching for the other number is what produced the confusion,
and a fallback that fires silently is worse than a blank. New reader fields: `age_hours`,
`headline_usable`, `headline_reason`. *A policy written as string interpolation is a policy
nothing can test.*
**`+818 since 250,000` deliberately NOT shown** - correct arithmetic that would read as Track 1
making money. Track 1 has sent no orders. Legacy realised P&L and return blanked in this mode too.

### TWO THINGS MEASUREMENT FOUND ON THE WAY
1. `/api/v1/runner-state` reports **`freshness: "fresh"` at age_seconds=288,670 (80.2h)**. The
   label asks the SCHEDULE whether a publish was due; in track1-only mode the legacy runner is
   never due. The zone dims on that label, so it never dimmed. *A freshness model that assumes
   its producer still runs cannot report a producer that has stopped.* Legacy contract left
   alone; this card measures age itself past `LEGACY_STALE_HOURS = 12`.
2. The recorded account note still says **"read 0 minute(s) ago"** about an 11:29Z record read
   at 15:10Z. Age is now computed when asked.

### BACKEND RESTART **IS** REQUIRED - AND THE BUG THAT NEARLY SHIPPED
The endpoint imports its reader INSIDE the view, which looks like it reloads per request.
Python caches the module. Asked the running pid 6420:
  `age_hours: null  headline_usable: null  headline_reason: null`
Read naively, null is falsy -> the page would have printed **"baseline FAIL" over a funded,
reconciled, PASSING account** the moment it shipped ahead of a restart. **Worse than the lie
being fixed.**
FIX: the page separates **ABSENT from FALSE**. Absent -> derive from what the old block carries.
False -> the backend decided, and it stands. Both halves tested, both red under mutation.
*Same correction as 5ZZE, where I inferred from file mtimes and was wrong. This time I asked.*
  `python monitor\ops.py restart --backend`  (NOT RUN - operator's call; any quiet window;
  **scheduler must NOT be restarted** and was not)

### ISSUES: SORTED BY WHOSE PROBLEM IT IS
All 5 still listed, top rail still counts all. Groups **Track 1 / Shared / Legacy**. Chip
`SCHEDULER` -> **`SHARED`** (SCHEDULER names a component; the chip answers a different question).
DEBT joins Legacy; an unknown scope lands in Shared where it stays visible. Panel row added:
**Blockers come from** the gate registry - 4 of 5 issues are legacy and nothing said so, so the
natural reading was five blockers. It is two.

### WIDTH, MEASURED IN A REAL BROWSER
                        375px  720px  1440px
  legacy headline         0     17      0     <- pre-existing
  track1 (before fix)    41     59      0     <- MINE
  track1 (after fix)      0     17      0
Two `white-space: nowrap` rules, both written when the headline was short. Both wrap below
1100px. **Wrapping not ellipsis** - a truncated money figure still looks like a money figure.
Residual 17px = a tooltip pseudo-element, identical in both states, does not scroll the page;
tested as a **property** (the new headline is never wider than the old) rather than a literal.

### ALSO FIXED: `from 76.8h ago ago`
`age()` already ends in "ago"; both legacy branches appended a second. Live since 5ZZF. No test
looked past the number.

### TESTS
**36 new**, 0 broker contacts, 0 runtime writes. **9/9 mutations RED**, subprocess, byte-identical
restore, exit 5 never counted as red.
One mutation **failed to go red first time** - a hole in my TEST DATA: the fixture's
`total_return` was null so both branches rendered `--` and the test agreed with the mutation that
deleted the guard. Second stage running where a mutation caught a test proving less than its name.
**4 pins restated, not weakened** (3 in test_realtime_dom, 1 in 5ZZF): the clause became
`Legacy runner state stale:` - it says WHY. Invariants unchanged: own name, never without its
age, no doubled word, nowhere outside its clause (checked by cutting the clause out).
*Care: the NEGATIVE pin contains the POSITIVE one as a substring - wrong order would have left a
plausible sentence asserting something else.*
  dashboard backend + contract + DOM + 5ZZH   **303 passed**
  ops status + 5ZZE + 5ZZF + test_ops          **84 passed**
**Pre-existing failures: 0.** Nothing left red.

### Files touched
NEW: scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py,
     scratch/track1_stage5zzh_dashboard_hygiene_20260827.{md,json}
MOD: monitor/backend/track1_runtime_reader.py, global_index/dash/realtime/realtime.js,
     global_index/dash/realtime/realtime.css, monitor/test_realtime_dom.py (3 pins),
     scratch/test_track1_stage5zzf_*.py (1 pin), pipeline doc, TASK.md
RUNTIME WRITES BY THIS STAGE: **none**

---

## Task: Stage 5ZZI - the feed went quiet, and the field that could not say so
Status: DONE (2026-08-27). **NO ORDERS.** No confirmation file, TRACK1_ORDERS_APPROVED never
set, no orders dir, nothing restarted, **no runtime evidence modified or deleted**. One
read-only IBKR probe, client id 95, reported before it ran.

### THE SEVEN ANSWERS
1. Root cause? **The bar feed returned no bars.** Not dropped, not filtered, not late - never
   delivered. Every gate condition is a restatement of that one fact.
2. Which condition failed? DECIDE `missing_session, stale, partial_coverage`; OBSERVE those
   plus `entry_quote_absent`.
3. Fix class? **PROVIDER_LAG** (external, operator action, no code change) + **EVIDENCE_BUG**
   (fixed here).
4. Was the refusal correct? **YES** - reproduced offline with the same codes, and the same rule
   ALLOWS both phases the moment bars are present.
5. Code changed? **The evidence path only.** No requirement, threshold, window or strategy rule.
6. Operator action? **YES** - only one TWS/Gateway login may hold this account.
7. Tests? **19 new, 6/6 mutations RED**, 164 passed in the named suites, 7 pre-existing.

### NOT CALM, NOT THE SCHEDULE, NOT THE ROLL
  NKD 01:10-02:55 ET   1,806 -> 1,910 rows/slot   normal
  MES/MNQ 09:32, 10:02          0 rows            both Calm phases
  MNQ 10:35 onward              0 rows            Stress, same
  last fetch WITH rows   2026-08-27T06:55:35Z  TRACK1_NKD_0255  MNKD 1,910
  first fetch WITH NONE  2026-08-27T07:05:10Z  TRACK1_CALM_1000  MES     0
Boundary between 02:55 and 03:05 ET. Yesterday the same instruments fetched fine. Front month
202609, next roll 2026-09-11.

### WHAT THE FEED WAS SAYING (read-only probe, client id 95)
  IBKR code=162: Historical Market Data Service error message:
                 Trading TWS session is connected from a different IP address
  MES rows=0  MNQ rows=0  NKD rows=0
The account's session is held from another address; IB restricts historical data while it is.

### THE PART THAT IS A CODE DEFECT
`_fetch_raw` returns `pd.DataFrame()` on BOTH `if not bars` and inside `except Exception`, and
ib_insync does not raise on 162 - it emits on an event and returns an empty list. **A refused
request and a quiet market arrive identical**, and the difference is gone before anything can
record it. Three days of rows said "there were no bars" when the truth was "the service
declined". Same family as the process scan returning `[]` for both "none running" and "could
not look": **an empty answer standing in for an error.**
FIX, three hops: provider listens on errorEvent and keeps the named refusal ->
`JoinedFrame.provider_error` carries it -> the observation row emits it, **or None when the feed
genuinely said nothing.** Deaf to unrelated chatter (2104 etc). Fail-soft on: no `_ib`, an event
that will not attach, an attribute that raises. Handler removed in `finally`.

### REPRODUCED BOTH WAYS, OFFLINE, NO NETWORK
  provider silent    DECIDE/OBSERVE  ALLOW=False, codes == recorded exactly
  provider answering DECIDE/OBSERVE  **ALLOW=True, codes []**
The second run settles it: the requirement is satisfiable and the clock is right.
Detail worth keeping: the parquet stops at yesterday 13:44, so yesterday's 13:45-16:00 arrives
on the SAME live fetch - which is why the request is `2 D`. A stub offering only today leaves
`partial_coverage` standing and would "find" a requirement bug that is the stub's own shape.

### VERIFIED vs INFERRED
VERIFIED: every fetch from 03:05 ET zero; the boundary; the gate codes and their reproduction;
that the probe got 162 and zero rows on all three.
INFERRED: that 162 answered the 09:32/10:02 fetches **specifically**. The probe ran later and
those rows cannot say - **because the field did not exist**. Strong, and exactly the inference
nobody should have to make. From the next fetch on, the row says it outright.

### OPERATOR ACTION - NO CODE WILL FIX THIS
  1. Log out the other TWS/IB Gateway holding this account (paper and live = same login)
  2. Confirm with a read-only fetch; the row now carries the reason if still refused
  3. Until it answers every slot refuses - CORRECT: the day classifies incomplete, does not count
Nothing to restart. **Do not clear the refusals** - they are the record of a day the feed was down.

### THREE DEFECTS THE TESTS FOUND IN MY OWN WORK
- `as_dict` did not carry the new field: a field added to a dataclass and shown to nobody -
  the same defect one storey up from the one being fixed
- the mutation harness **silently SKIPPED 3 of 6**: these files are CRLF, so any anchor with a
  bare newline matched nothing, and a skip prints as "we tried" while proving as much as not
  running it. Caught by reading the output, not the summary line
- `hasattr` only swallows AttributeError, so a property raising anything else took the whole
  fetch down; the attach is now guarded outright

### TESTS
19 new, 0 broker contacts, 0 runtime writes. The four the stage named + the evidence half.
**6/6 mutations RED** (listener stops collecting · as_dict drops it · absent becomes "" ·
handler left attached · DECIDE may ask for its own forming bar · OBSERVE stops needing the
quote), source-level in a subprocess, every file restored byte-identical, exit 5 never counted
as red.
**7 pre-existing failures** in 5ZA/5ZB - the deferred Calm slot-split roster pins (`71 == 70`,
`roska4_calm 2 vs 1`, DECIDE gated with the unsplit 10:00 rule). Neither suite reads a field
this stage touched.

### Files touched
NEW: scratch/test_track1_stage5zzi_calm_live_bar_refusal_20260827.py,
     scratch/track1_stage5zzi_calm_live_bar_refusal_20260827.{md,json}
MOD: global_index/track1_live_source.py (provider keeps the feed's words; JoinedFrame carries
     them; as_dict hands them on), global_index/track1_data_observation.py (the row emits
     provider_error), pipeline doc, TASK.md
RUNTIME WRITES BY THIS STAGE: **none**

---

## Task: Stage 5ZZG - the SEND wire exists, and the proof it stays shut
Status: DONE (2026-08-27 ET 10:05-10:45). **NO ORDER SENT.** No confirmation file,
TRACK1_ORDERS_APPROVED never set, no orders dir, **nothing restarted**, no broker order path
exercised outside tmp_path stubs.

### THE SEVEN ANSWERS
1. SEND wire implemented? **YES** - `track1_paper_send.maybe_send_orders`, called by the slot
   after the coverage row.
2. Can the scheduler reach it? **NO** - not without a manual `--allow-orders`, which no
   scheduler or ops path can produce.
3. Can a manual live-shadow run reach it with gates open? **YES**, and only then.
4. Any broker order sent? **NO** - every broker in every test is a stub.
5. Runtime order journal created? **NO** - `track1_runtime/orders` still ABSENT; every journal
   lived in a tmp_path.
6. Blockers remaining: **B1 + PAPER_SHADOW_EVIDENCE**, orders_possible **False**.
7. Tests: 33 new + 4 restated; **221** order-layer, **113** ops/dashboard; 4 pre-existing
   failures classified, none introduced.

### THE SHAPE, AND THE ONE THING THAT MAKES IT PROVABLE
  coverage row -> maybe_send_orders(decisions, order_gate, broker, ...)
     gate shut -> return; **nothing imported, nothing built, nothing written**
     gate open -> executor(broker, gate) -> open_position per ADMITTED decision
**The gate check sits ABOVE the import.** A SUBPROCESS test asserts the order layer is not in
`sys.modules` after a closed-gate call - which only means something while the import stays below
the check - and a second test pins the ordering by AST so the first cannot stop proving anything.
**It never constructs a broker**; armed with none it REFUSES (a second connection on a second
client id is how this project lost six entry slots in a morning). **It decides nothing** - the
word for "admitted" is asked of the signal layer that owns it.

### A HARDCODED CLAIM REPLACED BY A MEASUREMENT
`print("send_order calls: 0")` was true every day it was printed, and true **because nothing
could send**, not because anything had counted. Now the send pass's own summary:
  `send_order calls: 0 - the order gate is closed; no executor was built and no broker was called`

### FAILURE IS NEVER A REJECTION
A raising broker -> executor writes UNKNOWN and re-raises -> counted **unknown, never rejected**,
run marked fatal, `main` returns **3**: *"the order may be live and simply invisible."*
One bad send does not hide a good one.

### VERIFIED AGAINST THE REAL ENTRY POINT
  `--allow-orders` vs the real closed gate -> **EXIT 2, mode armed_but_refused**, refused BEFORE
     any provider or broker was built; orders dir still absent
  ordinary shadow slot -> **EXIT 0**, `send_order calls: 0 - the order gate is closed...`,
     shadow_intent md5 unchanged, orders dir absent

### A BUG I INTRODUCED, AND THE MEASUREMENT THAT BOUNDED IT
I added the new parameter **to the wrong function** - `broker=None` landed on
`emit_explanations`, so `main` passed args `observe_live_slot` did not accept: **every
live-shadow slot would have raised TypeError.** Found by RUNNING the entry point, not by
re-reading the patch. Bounded by the log, not the clock:
  broken window ~10:10-10:26 ET | last live-shadow slot before it **10:02** (completed OK) |
  next scheduled **10:35** | **track1 failure lines in today's log: 0** -> no live slot hit it.

### THE LIVE CALM PHASES RAN THIS MORNING - AND BOTH REFUSED
Listed as pending by 5ZZC/5ZZD/5ZZE. It happened:
  09:32:06 ET DECIDE  `gate_refused: missing_session, stale, partial_coverage`
  10:02:10 ET OBSERVE `gate_refused: missing_session, entry_quote_absent, stale, partial_coverage`
Both left a `REFUSED / gate_refused` row; the day classifies **incomplete** and does not count -
the machinery working, the refusal IS the record.
**NOT the stale daily file** (fixed before the window; `freshness_refused` is not among the
reasons). `missing_session` = today's session bars were not in the frame the gate was handed.
**NOT TRACED, AND NOT GUESSED AT** - next thing to investigate.
*I also misread the clock and briefly attributed these rows to my own test runs. They are the
scheduler's (13:32:06Z / 14:02:10Z). Corrected by reading the row timestamps.*

### OLD INVARIANTS RESTATED, NOT WEAKENED
4 tests held "nothing imports the executor" / "the slot has no order gate" - true while the wire
did not exist, false now BY DESIGN. Weakening to "anything may import it" would throw away the
only thing that notices a second road to a broker. Now:
  - the executor may be named by exactly the listed modules: one **WALLED** (RefusingBroker),
    one **GATED** (import past the check)
  - the slot's gate argument **exists, DEFAULTS TO SHUT**, and the scheduler passes nothing
    -> a better test than the one it replaced: nobody was watching the default before, because
       there was no default to watch
Care needed: the 5W scan EXCLUDES the dry-run callsite by name, so ITS allowed set is one entry;
listing both there would be a truer-sounding sentence about a scan that never looks at the
second. The full picture is asserted in the 5ZZG suite over an unfiltered scan.

### TESTS
**33 new**, no broker contacted, every journal root a tmp_path, no test arms the gate or sets the
approval flag - and one test asserts that about the session it runs in.
4 mutations all RED: gate stops being checked · unknown counted as rejected · unadmitted
decisions sent · the scheduler gaining the flag.
Stub broker needed all five methods `broker_capability_report` names (measured, not guessed - the
first version missed two and every armed test failed at construction), and `on_submit` is a
NAMED parameter because `accepts_receipt` inspects the signature.
**4 pre-existing failures** in 5D (the Calm slot-split bucket) - classified against the recorded
list from three stages ago.

### Files touched
NEW: global_index/track1_paper_send.py,
     scratch/test_track1_stage5zzg_order_send_wire_20260827.py,
     scratch/track1_stage5zzg_order_send_wire_20260827.{md,json}
MOD: global_index/run_live_day_track1.py (order_gate + broker on observe_live_slot, the send
     call, the real summary, exit 3 on unresolved), scratch/test_track1_stage5w_*,
     test_track1_stage5z_callsite_dryrun_*, pipeline doc, TASK.md
RUNTIME WRITES BY THIS STAGE: **none** (today's shadow_intent rows are the scheduler's).

---

## Task: Stage 5ZZF - the page was subtracting across a currency boundary, three days late
Status: DONE (2026-08-27 ET 07:45-08:10). Source/tests/docs only. No orders, no confirmation
file, no orders dir, **nothing restarted**, **no runtime evidence edited**, no broker connection
(the already-served API was enough).

### 1. WHY THE OLD EQUITY WAS STILL VISIBLE
The line read `Broker acct $996,731 / -$3,749 since 2026-07-08`. **Two faults:**
- **THE SUBTRACTION CROSSED A CURRENCY BOUNDARY.** `meta.paper_start` carries its own note
  *"connect_test_paper.py, DUR125337, CAD"*; `meta.broker_equity` carries **no currency at
  all**. The difference was printed with a `$` on a page where everything else is USD, about
  the account DUR125337 which now holds USD.
- **IT WAS 76.8 HOURS OLD AND THE PAGE COULD NOT TELL.** Envelope said
  `freshness: not_expected_yet` (NOT stale), `age_seconds: 276,575`, `expected_next_at` in the
  FUTURE - because in track1-only mode the legacy runner is **never scheduled**, so the expected
  time keeps sliding and nothing calls it old. The page's guard
  (`['missing','unknown','stale'].includes(freshness)`) **never fired in three days**.
  *A freshness model that assumes its producer still runs cannot report a producer that stopped.*

### 2. AUTHORITATIVE SOURCE NOW
  account the route starts from -> **`track1-runtime.paper_account`** (USD 250,818, PASS)
  live broker -> `/api/v1/broker.payload.equity` **only when fresh**, labelled `broker now`
     (measured drift between the two: **$0.27** - exactly what the label exists to permit)
  legacy figure -> only under **"Legacy runner state"**, ALWAYS with its age, never as current
  divergence >10% -> the line names it, gives the age, and turns negative
  **The account line no longer consults `runner.freshness`** - it uses the AGE, a fact, rather
  than a schedule that in this mode is a fiction.

### 3. OPEN ISSUES: RECLASSIFIED - **NOTHING DELETED, HIDDEN OR DOWNGRADED**
5 in, 5 out; each keeps status, evidence, occurrences and place. Each gained 3 fields:
  scheduler  job:session_report:missed            | legacy  paper:lifecycle:unresolved
  legacy     paper:pnl:paper_flex_total_mismatch  | legacy  paper:decision_path:unresolved
  known_debt known_debt:model_age                 | **track1_readiness_blocker=False on ALL**
The three `paper:` issues compare the LEGACY ledger and read no Track 1 artefact - said on the
chip and in its tooltip. Scope **derived from the key**, not a hand-kept list of titles.
Payload declares `track1_readiness_blockers_come_from = track1_gates.blocking()` - *a log parser
holding a second opinion about what stops orders is how two answers come to disagree.*
Visual: **one chip in the EXISTING badge lane**, same pill geometry; legacy/debt lanes quieter
than TRACK 1. No new section, no new card.

### 4. RESTART - **BACKEND YES** (issue chips only), scheduler no
  backend PID 42260 started **07:08:35 ET**
  open_issue_reader.py edited **07:56** -> **NOT served** (imported at module top, app.py:39)
  track1_runtime_reader.py edited 07:24 -> IS served (imported INSIDE the handler, app.py:249,
    and only because nothing had called that endpoint between the restart and the edit)
**This CORRECTS 5ZZE**, which said no backend restart was required: the measurement was right and
the conclusion too general - that block was served by luck of import ordering, not a reload.
JS/CSS are static -> a browser refresh suffices for the equity line and chip styling.
  `python monitor\ops.py restart --backend --yes`  - NOT run, operator's call.
Nothing worse meanwhile: every issue still listed, simply without its chip.

### 5. ORDERS / BLOCKERS - UNCHANGED
orders_possible **False** | B1 + PAPER_SHADOW_EVIDENCE | confirmation ABSENT | orders dir ABSENT

### 6. TESTS
**18 unit + 5 new browser tests** driven with the exact numbers that were on the page.
3 reader mutations RED (legacy issue promoted to Track 1 · scoping filtering instead of
labelling · the parser declaring its own blockers). 2 page mutations RED, file restored
byte-identical (account line reverting to the legacy number -> 3/5 browser tests fail; the
divergence threshold removed -> 1 fails).
Suites: **287 passed** (DOM + contract + dashboard backend), **144 passed** (adjacent Track 1).
**1 pre-existing test REWRITTEN, not deleted**: `test_broker_account_delta_is_visible_in_equity_
header` asserted the delta `4,168` - it pinned **the very behaviour this stage removed**. Its
concern (a sharp divergence must be visible) is kept, now measured from the BASELINE.

### FOUR FAULTS FOUND BY RUNNING, NOT READING
1. **A substring assertion read my own comment** - `"Broker acct" not in JS` found the phrase in
   the comment recording that it was wrong. **Fourth time in this project.** Reader now strips
   comments, AND a second assertion demands the comment still exists.
2. **A slice with no end** - `JS[i:i+3000]` ran past the account line into another function.
3. **A cached reader made a mutation a no-op** - `read_open_issues` memoises; the builder was
   never called and the test passed proving nothing. Cache cleared + non-empty assertion added.
4. **PRODUCTION**: `_build` called `_scoped(issues)` for its **side effect** then read `issues`
   again - works while it edits in place, fails silently the day it returns a new list. The
   mutation turned a wrong answer into a KeyError. Caller uses the return value now.

### Files touched
SOURCE: dash/realtime/realtime.js, realtime.css, index.html, monitor/backend/open_issue_reader.py
TESTS: scratch/test_track1_stage5zzf_...py (new), monitor/test_realtime_dom.py
DOCS: scratch/track1_stage5zzf_...{md,json}, pipeline doc, TASK.md
RUNTIME EVIDENCE: none. BROKER CONNECTIONS: 0. RESTARTS: 0.

---

## Task: Stage 5ZZE - B1 was vouching for an account that no longer existed
Status: DONE (2026-08-27 ET 07:20-07:35). New account-baseline layer + read-only broker
reconcile + ONE runtime record. No orders, no confirmation file, no approval flag, no order
path, **nothing restarted by this stage**, **no shadow/dashboard evidence cleared**.

### VERDICT
paper_account_baseline_recorded **YES** (PASS account_flat_and_funded)
account_currency **USD** (single: {'USD': 250817.91}) | account_equity **250,817.91** (0.33%
from 250k) | broker_positions **0** | broker_working_orders **0**
legacy_book_flat **YES** | track1_book_flat **YES** (schema 2, route-stamped)
b1_evidence_fresh **YES - but it was describing the WRONG ACCOUNT**
readiness_gate_changed **YES** | dashboard_updated **YES** | orders_possible **FALSE**
runtime_files_touched **ONE** (account_baseline_20260827.jsonl)
next_action **Calm DECIDE 09:32 ET still pending; re-record baseline within 24h**

### THE MEASUREMENT THAT MADE THIS NECESSARY (taken BEFORE writing code)
  B1 record 2026-08-26 11:34 ET | age **19.77h - INSIDE its own 24h window, still PASS**
  recorded equity **996,875.91** | currency **recorded nowhere in the row**
  stated baseline 250,000 | **drift 299%**
**The account had been reset underneath a PASS.** B1's freshness window is about POSITIONS AND
ORDERS, and a reset changes neither - so it went on saying "flat and safe" about an account that
no longer existed. Both books WERE genuinely flat (state=read count=0). **Flatness was never the
problem. Identity was.**

### `get_equity()` COULD NOT HAVE CLOSED IT
Its own docstring: *"Accept any currency (CAD/USD/BASE accounts all work)"*; the code prefers
BASE, then whichever of USD/CAD is listed first, then anything - returning a **bare float**. A
baseline on it would record "250000" for 250,000 **CAD**. => the probe reads `accountValues()`
and keeps EVERY currency-tagged NetLiquidation, label attached all the way into the record.

### THE BROKER READ (read-only, client id 96 - stated before connecting)
96 is distinct from legacy 1 / slot child 89 / safety 90 / b1_audit 97.
  `BASELINE : PASS: USD 250,817.91, no positions, no working orders, both books flat and
   route-stamped, read 0 minute(s) ago` | account DUR125337 | currencies {'USD': 250817.91}
**The reset landed**, and it confirms the finding: yesterday 996,875.91, today 250,817.91.

### CONTRACT (decided and documented)
  currency != USD -> FAIL | equity <= 0 -> FAIL | drift >25% -> FAIL | >5% -> **WARN** |
  <=5% -> PASS | anything unread -> UNKNOWN | B1 not PASS -> FAIL/UNKNOWN |
  observation >30min -> UNKNOWN | record >24h -> UNKNOWN
**Only PASS satisfies the gate.** WARN refuses too - the difference is what an OPERATOR does
next, not what the gate does. (5% of 250k = 12,500: wide enough for fees, narrow enough to hide
nothing. 25% = 62,500; the reading that prompted this was 299% away.)
Books are consulted **through B1**, never re-implemented - two implementations of "is it flat"
is how they come to disagree.

### WHERE IT LIVES
`global_index/track1_runtime/account_baseline/account_baseline_YYYYMMDD.jsonl` - **durable, not
scratch** (a baseline the gate cannot read is not a baseline). **Append-only** so "when did this
account last look right" stays answerable. Every row carries: *zero positions is attributable to
every route; a non-zero count to none.*

### GATE
new check `paper_account_baseline` -> **PASS**. orders_possible still **FALSE**, blocking B1 +
PAPER_SHADOW_EVIDENCE. **No confirmation file, no approval flag, no orders dir.**
**B1 unchanged as a gate** - still decision + measurement; nothing here signs it or auto-creates
a retirement confirmation.

### AN INFERENCE I NEARLY REPORTED AS FACT
Scheduler+backend were restarted **07:08 ET by the operator**, and every file I touched was
written 16-18 min AFTER. From mtimes I concluded the running backend could not serve the new
block. **Asking the endpoint said otherwise** - it serves `paper_account`, correctly populated.
*An inference from file times is not a measurement of a process* - the lesson from two stages
ago, applied to its own author. **No backend restart required.** Same check confirmed audits,
window_coverage and signals all survived.

### THE RESTART HAD ALREADY HAPPENED
Scheduler PID **14344**, started 07:08:32 ET via ops.py, and its log shows it registered
`spy_refresh_pm_r1`, `spy_refresh_pm_r2` AND `spy_last_chance_pre_nkd`. **The restart 5ZZC and
5ZZD were waiting for is DONE; both are live.**

### TWO FAULTS IN MY OWN NEW CODE, BOTH FOUND BY MUTATION
1. `operator_line` **crashed** (TypeError) on a PASS with no account block - it formatted the
   equity unconditionally. That would have taken the whole readiness call down. *A reporting
   function that can crash turns a mild problem into no report at all.*
2. `MAX_RECORD_AGE_HOURS` **looked like a setting and was not** - written into `latest()`'s
   signature as a default argument, evaluated once at definition, so patching it changed nothing
   and a stale record still read back as PASS. Now resolved at call time.

### TESTS
**36 pass**, nothing connects, every broker reply stubbed. 5 mutations all RED (currency
discarded · WARN satisfying the gate · stale read as PASS · unreadable flattened into absent ·
readiness accepting a baseline never recorded). Notable: **the 996,875.91 B1 actually recorded
FAILS today** · recording a baseline **clears no shadow evidence** · a dashboard 0/0 snapshot is
**not** accepted as a broker reconcile · the connecting tool is outside the gate-scanned prefix
with no order path and its own client id.
Suites: **259 passed** (track1+ops), **220 passed** (dashboard backend + contract).
**2 pre-existing failures** in 5ZR (roster pins expecting REGIME_LABEL_VERIFICATION, released
08-26) - confirmed against the recorded list from two stages ago, not assumed.
**3 repairs, none loosened**: the ops-status check banned the STRING `UNKNOWN (` across the whole
output and this stage added a line legitimately using that shape with a real code -> scoped to
the process lines it is about; readiness fixtures grew an account baseline.

### Files touched
NEW: global_index/track1_account_baseline.py (pure, never constructs a broker),
     global_index/account_baseline_audit.py (**outside the `track1_` prefix on purpose** - 5ZQ
     closed the live-frame gate by naming a connecting module `track1_b1_audit.py`),
     scratch/track1_stage5zze_paper_account_baseline_20260827.{md,json},
     scratch/test_track1_stage5zze_paper_account_baseline_20260827.py
MOD: track1_paper_readiness.py, monitor/ops.py, monitor/backend/track1_runtime_reader.py,
     dash/realtime/realtime.js, scratch/test_track1_stage5s_*, test_track1_stage5zz_*,
     test_track1_dashboard_runtime_wiring_*, pipeline doc, TASK.md
RUNTIME: **one file** - account_baseline_20260827.jsonl at 07:29:47 ET. RESTART: none.

### REMAINING
1. **Calm DECIDE 09:32 / OBSERVE 10:02 ET - STILL PENDING** (it is 07:35)
2. PAPER_SHADOW_EVIDENCE - 3/5 days, 0 with Calm evidence, all three FAIL days
3. B1 - no decision; its measurement expires **11:34 ET today**
4. the SEND wire - does not exist
5. this baseline expires **11:29 ET tomorrow**:
   `python -m global_index.account_baseline_audit --broker ibkr --record`

---

## Task: Stage 5ZZD - the last look, and the Monday nobody was covering
Status: DONE (2026-08-27 ET 06:35-06:50). Scheduler + tests only. No orders, no confirmation
file, **nothing restarted**, no runtime file touched, **production spy_daily_live.csv NOT
touched** (md5 80f06253... unchanged).

### VERDICTS
pre_nkd_last_chance_built **YES** (`spy_last_chance_pre_nkd`, 00:45 ET mon-fri, 25 min before
NKD 01:10) | required_date_logic **previous TRADING day, ASKED of track1_freshness**
no_op_when_covered **YES** (returns before the command is built) | final_missing_is_loud **YES**
(ERROR, names file+day+who it stops+the command) | scheduler_restart_required **YES** (same
restart 5ZZC needs) | orders_possible **FALSE** | production_spy_csv_touched **NO** |
runtime_files_touched **NO**

### TWO QUESTIONS THAT LOOK LIKE ONE
Evening ladder asks for **the day that just closed**. This asks **the day the sleeves about to
run will demand**. Tue-Fri identical; **on a MONDAY they are not** - the demanded day is the
FRIDAY, and the last evening rung ran Friday 17:15, **31 hours earlier**. Nothing between
Friday 17:15 and Monday 01:10 had ever looked. **That Monday gap is the hole.**
Measured over 16 consecutive days: the 00:45 computation and what NKD needs at 01:10 agree on
**every** one, incl. Labor Day (Tue 09-08 asks 09-04, skipping the holiday 09-07).
It guards NKD **and both Calm phases** - everything before the 13:45 pre-flight reads this file.

### ASKS THE GATE, READS THE MARKET'S CALENDAR
  `need = _fresh.required_daily_close_through(_pd.Timestamp(_et_today()))`
- **not** a local calculation: a second copy of "which day is needed" drifts from the gate that
  refuses, and then the job reports fine about a morning the gate will stop.
- **`_et_today()` not `date.today()`**: that helper's own docstring records the measurement -
  *west of ET the 01:10-02:55 slots land on the PREVIOUS local date* - and a 00:45 job is
  exactly where that bites. Both pinned by a test reading the job's source.

### THREE OUTCOMES, ONE LOUD
  covered   `nothing to do - the daily series covers <day>...` - **launcher never called**, no
            fetch, no API key, cannot fail. Comparison is **>=** not ==.
  recovers  `RECOVERED at the last look - ... The 17:15 rung is running before the provider is
            ready on at least some days.` **WARNING on purpose**: a last chance that keeps
            saving the evening is an evening schedule that wants moving.
  missing   **ERROR** `SPY daily file is missing <day>; NKD/Calm freshness-bound slots will
            refuse unless manually refreshed. ... nothing else looks until the 13:45 pre-flight,
            which is after both Calm phases. Re-run: <command>`
            Own label `SPY_LAST_CHANCE_PRE_NKD` - a test asserts it never wears the evening
            rung's name. Evening = "a morning is at risk"; this = "the morning is lost now".

### STATUS/DASHBOARD - NO CHANGE NEEDED
Both already compute the requirement from the same freshness module, so at 00:45 they name the
same day. Dashboard row still says *"a stale daily-context warning, **not a slot failure**"* -
kept apart from the window verdict (NKD 08-27 = PASS 22/22 while diagnostics said stale).

### TESTS
**21 pass**, no network, nothing outside tmp_path, production series read never modified.
**2 REAL mutations** (calendar replaced so the requirement becomes the session's own day; so the
holiday stops being skipped) - both RED.
**2 SOURCE GUARDS, labelled as such and NOT counted as mutations**: the branches live inside a
closure unreachable from outside, so they assert a source property (final shortfall still at
ERROR; the no-op comparison not inverted/narrowed). **A source guard catches an edit, not a
behaviour** - weaker, and said so rather than letting anyone count four.

### A PIN I BROKE AND REPAIRED IN BOTH DIRECTIONS
5ZZC's test pinned the scheduler's **total size** (63/133/104); this stage broke it by adding one
**unrelated** job. That is the roster anti-pattern already on record - a pin failing for
something it is not about teaches its reader the failure is noise. Repaired as a **property**
(the ladder is its three named rungs). And **this stage's own equivalent test was rewritten the
same way before it could rot** (the SPY family is four named jobs).
Inventory measured: 63->64, 133->134, 104->105 (+1) - recorded, but the TESTS assert the family.

### RESTART - REQUIRED, SAME ONE AS 5ZZC
One restart brings the retry rungs AND this job live. Nothing worse meanwhile.
**Window 12:40-13:45 ET** (measured 65-min gap, after the Stress audit, before the pre-flight,
after both Calm phases are watched).
  `python monitor\ops.py restart --scheduler --track1-only-shadow --yes`
Verified: `--shadow-resume` is the default on that path -> argv byte-identical to PID 5856.
NOT RUN - operator's call.

### STILL PENDING FROM 5ZZC
Calm DECIDE 09:32 and OBSERVE 10:02 **not yet observed** (it is 06:49 ET). Nothing here touches
those phases; the baseline recorded this morning is unchanged.

### Files touched
NEW: scratch/track1_stage5zzd_pre_nkd_spy_refresh_20260827.{md,json},
     scratch/test_track1_stage5zzd_pre_nkd_spy_refresh_20260827.py
MOD: global_index/run_scheduler.py, scratch/test_track1_stage5zzc_* (pin -> property),
     pipeline doc, TASK.md
PRODUCTION DATA: none. RUNTIME: none. RESTART: none.
Suites after: **206 passed**.

---

## Task: Stage 5ZZC - a retry ladder, and the measurement that stopped it becoming noise
Status: A+B DONE, **C PENDING** (2026-08-27 ET 06:10-06:30). No orders, no confirmation file,
**nothing restarted**, no runtime trading file touched, **production spy_daily_live.csv NOT
touched by this stage** (md5 80f06253... unchanged; the operator's manual refresh landed first).

### VERDICT
spy_daily_now_covers_required_day **YES** (last=2026-08-26 required=2026-08-26)
retry_schedule_built **YES** (16:20 primary + 16:45 + 17:15)
scheduler_restart_required **YES** | calm_decide_observed **NO - PENDING 09:32 ET**
calm_observe_observed **NO - PENDING 10:02 ET** | orders_possible **FALSE**
runtime_files_touched **NO** | production_spy_csv_touched_by_stage **NO**
next_action **watch 09:32 + 10:02, then restart in the 12:40-13:45 ET window**

### PART A - THE MEASUREMENT THAT SHAPED THE LADDER (taken BEFORE writing it)
A retry with nothing to do - **the SUCCESSFUL case, every good day** - **exits 1**:
  `regime verification: UNKNOWN (no_snapshot): the series already ends at 2026-08-27, so
   nothing was fetched and no snapshot comparison was made` -> strict fails on it.
Two rungs a day each reporting FAILED on every day that went WELL = an alarm that fires when
nothing is wrong. Building the ladder without noticing this would have made things **worse**.
=> `--skip-if-covered` short-circuits **before the fetch and before the API key is used**.
Proven with a deliberately invalid key: **EXIT 0**, provider never reached.
**Only the retries skip** - the 16:20 run still verifies the labels; that is part of its job.

### THE THREE RUNGS
  SPY_REFRESH_PM     16:20  --verify-strict --require-through <today>
  SPY_REFRESH_PM_R1  16:45  ... --skip-if-covered
  SPY_REFRESH_PM_R2  17:15  ... --skip-if-covered
Read back from REAL construction with the launcher replaced. **No rung and no Track 1 slot
carries `--allow-orders`.** No morning slot fetches SPY - they read the file; the gate refuses.
Inventory measured: legacy 61->63, transitional 131->133, track1-only 102->104. Exactly +2.

### FOUR OUTCOMES, FOUR MESSAGES
  primary lands it   `OK - the daily series now covers <today>`
  a retry lands it   `RECOVERED - ... the 16:20 refresh is running before the provider is
                      ready; if this keeps happening, move it later rather than relying on
                      the ladder.`  <- a WARNING on purpose
  retry no-op        `nothing to do - <day> was already in the series`
  middle rung short  `... Next attempt at 17:15 ET.`
  **last rung short  `LAST ATTEMPT - ... the overnight NKD window and BOTH Calm phases will
                      refuse on regime_csv: stale`**  <- loud because it has no successor
  run broke          FAILED, with drift / unverifiable / other told apart

### A HOLE I MADE AND CLOSED IN THE SAME HOUR
`_run` reports a dry run as success without executing, so my first rung judged itself against a
series nothing had touched and logged **a FAILED refresh for a command never sent** - a false
alarm invented by the mode whose whole point is to avoid side effects. Found by writing the
test for it, not by re-reading the code.

### PART B - THE DAILY FILE KEPT APART FROM THE SLOTS
status: `spy_daily_coverage=covers_required_day last=2026-08-26 required=2026-08-26`
dashboard: its own **`SPY daily`** row - `SPY daily file covers 2026-08-26`, or when short
  `SPY daily file is missing YYYY-MM-DD ... **This is a stale daily-context warning, not a slot
   failure**`. Evidence it matters: NKD 08-27 audit = **PASS 22/22 `all_slots_observed_no_action`
   judgeable:true** while its per-slot diagnostics said `freshness_allow=false`. Two true facts
   about different things. The bidirectional fact pin caught the new row at once.

### PART C - PENDING, NOT PRETENDED
It is **06:24 ET**; the phases run at 09:32 and 10:02. Baseline RECORDED so the after has
something to compare to: sched 5856 · coverage covers_required_day · slot table fresh 71/71 ·
orders_possible False · **orders dir ABSENT · shadow_intent ABSENT** · trade log 0 rows ·
book+checkpoint 08-27 02:55:42 ET · csv md5 80f06253.
DECIDE must show an intent OR an explicit `NO_SETUP/no_candidate` (**silence is the one outcome
not allowed**), **no entry price and no planned stop**, freshness pass or explicit refusal.
OBSERVE must read the DECIDE rows, price the reference at the 10:00 open, derive the stop FROM
it. **How to tell a real quiet day from a data problem**: `NO_SETUP/no_candidate` = the rule
looked; `REFUSED/freshness_refused` = the rule was never asked; no rows = the phase did not run.

### RESTART - REQUIRED
The running scheduler (PID 5856, started 04:08 ET) holds the OLD single job. **Nothing is worse
meanwhile** - tonight's 16:20 behaves as yesterday and status says if it leaves the file short.
**Window 12:40-13:45 ET (measured 65-min gap** after the Stress audit, before the pre-flight,
and after both Calm phases are watched). Next best: 13:45-14:05 (20m), 10:20-10:35 (15m).
  `python monitor\ops.py restart --scheduler --track1-only-shadow --yes`
**Verified, not assumed**: `--shadow-resume` is the default on that path, so the new argv is
byte-identical to PID 5856's. NOT RUN - operator's call.

### TESTS
**22 pass**, no network, nothing outside tmp_path. Mutations all RED: retries losing the skip
flag · a covered retry reaching the provider · the skip flag passing a genuinely missing day ·
the last rung claiming a successor · daily context rendered as a window failure.
**Two of yesterday's tests RESCOPED, not loosened**: they asserted what the 16:20 job does and
the job is now a one-line delegator; widened to the shared body, they now cover all three rungs.
Suites after: **185 passed** (track1+ops), **220 passed** (dashboard contract+backend).

### Files touched
NEW: scratch/track1_stage5zzc_spy_refresh_retry_calm_watch_20260827.{md,json},
     scratch/test_track1_stage5zzc_spy_retry_ladder_20260827.py
MOD: global_index/update_spy_csv.py, global_index/run_scheduler.py,
     monitor/backend/track1_runtime_reader.py, global_index/dash/realtime/realtime.js,
     scratch/test_track1_dashboard_runtime_wiring_*, scratch/test_track1_stage5zzb_*,
     pipeline doc, TASK.md
PRODUCTION DATA: none. RUNTIME: none. RESTART: none.

---

## Task: Stage 5ZZB - the warning named its own escalation condition, nobody was reading
Status: DONE (2026-08-27 ET 05:05-05:35). Investigation + bounded fix. No orders, no
confirmation file, **nothing restarted**, no runtime trading file touched, **production
spy_daily_live.csv UNTOUCHED** (md5 d71f8ef6... identical before and after).

### VERDICT
spy_refresh_pm_success_claim_valid **YES - and it never claimed coverage; it WARNED**
spy_csv_last_date **2026-08-25** | required for NKD 2026-08-27 **2026-08-26**
root_cause **the escalation nobody owned** | fix_applied **YES**
production_spy_csv_touched **NO** | runtime_files_touched **NO** | orders_possible **FALSE**
next_action **refresh before 09:32 ET or TODAY'S CALM PHASES REFUSE TOO**

### THE BRIEF'S PREMISE NEEDED CORRECTING FIRST
Scheduler did NOT log silent success. It logged `completed OK` and **on the next line**:
  `WARNING [SPY_REFRESH_PM] ran cleanly but the daily series still ends on 2026-08-25, not
   2026-08-26 ... this is only a problem if it is still true tomorrow.`
Stage 5ZL had already removed the silent-success defect from this exact job.
**The defect is that last sentence**: the warning names its own escalation condition and
NOTHING LOOKS TOMORROW. Tomorrow came, NKD ran at 01:10, the condition was true.
(08-25 the same job at the same minute DID get the close. Same code, different provider luck.)

### WHAT `--verify-strict` ACTUALLY VERIFIED
Its own output: **"1761 label(s) compared through 2024-12-31"** - a DRIFT check over settled
history. Says nothing about last night's close. `appended==0` -> "already up-to-date" -> exit 0.
**Provider failures are NOT swallowed** (measured): bad key exits **1**, file untouched; empty
fetch records UNKNOWN which strict fails on.

### WHY THE FILE IS SHORT - PROVED AGAINST A TEMP COPY
`Updated spy_copy.csv: 1 new row(s), 2425 total (last=2026-08-26)` close 766.08.
**The provider HAS it now**; it did not at 16:20 ET yesterday - exactly what the warning said.
Refuted: wrong path · skipped write · timezone (14:20 MT = 16:20 ET, same calendar day) ·
holiday (Wednesday) · wrapper-not-verification (the wrapper DOES read the file's last date).

### CONTRACT, BEFORE -> AFTER
  BEFORE  --verify-strict: exit 1 on label DRIFT/UNKNOWN; coverage NOT examined; a clean run
          that supplied nothing exits 0
  AFTER   + `--require-through YYYY-MM-DD`, four states, own exit code:
          covers_required_day 0 | provider_did_not_return_required_day **2** |
          coverage_unknown **2** | coverage_not_requested 0
  **Exit 2 not 1 deliberately**: a data-supply gap and a moved history are different problems
  with different owners. Scheduler now passes `--require-through <today>` so the existing
  FAILED branch fires. **Takes effect at next restart; NO restart asked for** (the running
  scheduler already warns correctly, so nothing is worse meanwhile).

### THE READER FOR TOMORROW - `ops.py status`
  `spy_daily_coverage=provider_did_not_return_required_day last=2026-08-25 required=2026-08-26`
  `  SPY daily file is missing 2026-08-26 - it ends on 2026-08-25. Sleeves that run before the
     13:45 pre-flight (the overnight NKD window) will refuse on stale daily context...`
Asks `track1_freshness` for the requirement rather than restating it (a second copy drifts from
the gate that refuses). **Does NOT blame the window that passed** - NKD 08-27 was 22/22 slots
observed and all decided; a test pins the wording.

### A DEFECT OF MINE FROM 5ZX, FOUND BY WALKING INTO IT
**The phased Calm slots NEVER evaluated freshness** - measured, `freshness_allow=None`. 5ZX put
the phase early-exit BEFORE `fresh.evaluate`, bundling freshness with the admission machinery on
the reasoning "the decide half takes no position". **That reasoning does not reach freshness**:
it asks whether the INPUTS are current, which is as live for a half that records an intent as
for one that books a trade. Left alone, this morning's first-ever DECIDE would have recorded an
intent from a **two-day-old regime label** with nothing saying so.
FIXED and it BINDS: `decided=False reason=freshness_refused`, intent row **REFUSED /
freshness_refused**, `classify_day` -> **incomplete**. A counter can no longer reach five clean
days through days nobody would have traded on.

### => TODAY'S CALM WOULD REFUSE TOO (corrects an earlier draft of my own report)
  Calm DECIDE @09:32 allow=False regime_csv=stale (has 2026-08-25, needs 2026-08-26)
  Calm OBSERVE @10:02 allow=False  - the 13:45 pre-flight runs AFTER both phases.
**It is not only NKD that runs before its own pre-flight. Calm does too.**

### TESTS
**26 pass**, no network, nothing written outside tmp_path. 5 mutations all RED: short series
treated as success · unreadable read as covered · requirement moved to the session's own day ·
status reverting to the machine-readable flag · scheduler dropping the day from the argv.
Adjacent suites after: **202 passed**.

### MY OWN ERRORS THIS STAGE
1. **Piped through `tail` and read `$?`** - that is tail's exit code. First probe reported
   EXIT=0 for a run that threw SSL. Re-measured: a provider failure really exits 1. This
   project's own notes warn about exactly this and I did it anyway.
2. **Silenced the wrong logger twice** - a calendar import warning started appearing above the
   status header. First try silenced a LOWERCASE spelling of a logger that is capitalised;
   second try was the right logger at the wrong point in the call order. Now suppressed where
   the import happens and reported as a FIELD (`calendar=...`), not tidied away.
3. **Wrote that today's Calm was unaffected.** Measured: both phases refuse.

### Files touched
NEW: scratch/track1_stage5zzb_spy_refresh_coverage_20260827.{md,json},
     scratch/test_track1_stage5zzb_spy_refresh_coverage_20260827.py
MOD: global_index/update_spy_csv.py, global_index/run_scheduler.py,
     global_index/run_live_day_track1.py (the 5ZX freshness correction), monitor/ops.py,
     pipeline doc, TASK.md
PRODUCTION DATA: none. RUNTIME: none. RESTART: none.

### OPERATOR COMMAND - NOT RUN (writes production data)
  python -m global_index.update_spy_csv --csv spy_daily_live.csv --verify-strict `
         --require-through 2026-08-26 --api-key <key>
Deadline **09:32 ET** - after that today's Calm phases have already run.

---

## Task: Stage 5ZZ - ops status was telling the truth in a language nobody could read
Status: DONE (2026-08-27 ET 04:40-05:00). `monitor/ops.py` only. **Nothing restarted** (sched
5856 and backend 2108 before AND after), no orders, no confirmation file, no broker order path,
**no runtime file touched** (every mtime predates the stage).

### VERDICTS
ops_status_reliable **YES** | scheduler_restarted **NO** | backend_restarted **NO**
runtime_files_touched **NO** | orders_possible **FALSE** | next_calm_phase_ready **YES**

### IT DID NOT REPRODUCE - SAID FIRST, NOT LAST
`ops.py status` at stage start printed `scheduler_pids=[5856]` / `backend_pids=[2108]`, not
UNKNOWN. The fault is **intermittent**. This fixes why a failure is UNREADABLE when it happens
- which DID reproduce exactly.
**Timeout theory tested and KILLED by measurement**: probe = **0.63-0.73 s** over 3 runs on a
471-process host; filtering the query to python processes = **0.65 s, no better** (cost is
PowerShell startup, not enumeration). So the "obvious" narrowing was **NOT** made - it buys
nothing and would stop finding a scheduler launched under another interpreter name.

### ROOT CAUSE - MEASURED
reason was `stderr[:200]`, and PowerShell **echoes the whole command** before the message:
  stderr length **692** | first 200 chars = the script's own opening | message = **at the end**
=> operator saw `UNKNOWN (` + a fragment of their own script. The project's ops log has one
instance, **2026-08-13**, truncated in exactly that way, saying nothing.
**"Take the last line" is ALSO wrong**: the last line is the exception's CLASS NAME, and the
message itself is split across two lines by wrapping. Extractor built from the MEASURED shape;
recovers `Invalid class` from real output both with the new marker and without it.

### THE TRI-STATE WAS BUILT THEN THROWN AWAY ONE FUNCTION LATER
`ProcessScan` has 3 states on purpose (its docstring: collapsing them once started a second
scheduler on a live one). `scheduler_processes()` returns a **list**, and a list cannot say "I
could not look" - so a failed probe reached `track1_status` as `[]` -> `scheduler_running=False`
-> **`track1_mode=n/a`**: the health check saying Track 1 is off about a scheduler that is
running. Now True | False | **None**, and None prints `track1_mode=unknown` with the reason.

### OUTPUT CONTRACT
success: `scheduler_pids=[5856] source=process_table` · `track1_mode=... track1_mode_source=...`
         `track1_slot_table=fresh source_slots=71 registered_slots=71`
failure: `scheduler_process_scan=permission_denied: Access is denied.`
         `scheduler_pids=unknown_due_to_process_scan_error source=none`
         `backend_fallback=listeners:[2108] source=port_listener proves_running=True`
         `scheduler_fallback=last_registered_71_slots at ... machine-local source=log
          proves_running=False`
**Bare UNKNOWN is now impossible.** Codes: permission_denied / probe_timeout /
probe_unavailable / probe_failed / probe_no_output / probe_not_json.
**Today both pids are PROCESS-TABLE-derived.** No pid files exist in this project; the only
scheduler fallback is the log, and it **never** claims running (a log line is a history).

### THE CHECK THAT WOULD HAVE CAUGHT 5ZY-PRE
`track1_slot_table=` compares the count the running scheduler REGISTERED (its own log) against
the count the package DECLARES. Now `fresh 71/71`. Stale prints **RESTART NEEDED**. Works from
the log alone, so it still answers when the process table cannot be read.

### LATENT DEFECT FOUND WHILE FIXING
**The probe matched ITSELF** - the pattern is embedded in the probe's own command line, so any
pattern without a regex escape finds the process doing the searching. Both production patterns
are immune **by accident** (they escape their dots), and **`ensure_single` decides whether to
KILL from this same scan**. Closed, and pinned by a test that each pattern cannot match its own
source text.

### MY OWN MISTAKE, CAUGHT BY THE TESTS
First version had `track1_status` read the scan directly - **silently bypassing the seam every
existing test patches**. Five suites believed they had described a scheduler and were reading
the REAL MACHINE. *A test that is not isolated is worse than no test: it reports on the wrong
system with full confidence.* Rows come back through `scheduler_processes()`; the scan is
consulted only for its third state.

### CORRECTION TO THE 5ZY-PRE RECORD
That stage said **3** true 5ZX regressions. It is **4**. A third copy of the same argv extractor
lives in the ops-startup suite and failed with different wording (`_track1_body argv not found`
vs `no _run([...]) call found`), so grouping by reason string put it in the pre-existing bucket.
**It matters more than the count: that test asserts NO ORDER FLAG can reach a Track 1 slot, and
it had stopped running.** Repaired, widened the same way, and it now also pins the phase.
Corrected split: **45 slot-split / ~50 pre-existing / 4 true 5ZX regressions - all 4 repaired**.

### TESTS
**22 pass** (scratch/test_track1_stage5zz_...py) + repairs to 6 cases across 3 older suites.
5 mutations, all **RED**: probe exception read as a definite empty scan · printer reverting to
bare UNKNOWN · reason reverting to stderr[:200] · a 70-against-71 table called fresh · a log
line promoted to proof of running.
Adjacent suites after: **135 passed / 2 failed**, both failing BEFORE this stage (a
blocker-roster pin and an absence proxy).

### Files touched
NEW: scratch/track1_stage5zz_ops_status_process_reporting_20260827.{md,json},
     scratch/test_track1_stage5zz_ops_status_process_reporting_20260827.py
MOD: monitor/ops.py, scratch/test_track1_ops_status_mode_*, test_track1_stage5k_ops_startup_*,
     test_track1_stage5o_route_aware_safety_*, pipeline doc, TASK.md
RUNTIME: none. RESTART: none.

### NEXT
**2026-08-27 09:32 ET - TRACK1_CALM_DECIDE_0932**, first run of either phase in production
(scheduler restarted 04:08 ET, registered 71; status now says so on its own), then 10:02 ET
OBSERVE. Blocked before paper: PAPER_SHADOW_EVIDENCE (3/5, 0 with Calm), B1 (no decision; its
measurement expires 11:34 ET), the SEND wire (does not exist), machine sleep.

---

## Task: Stage 5ZY-PRE - the code is right; the running scheduler has never heard of it
Status: DONE (2026-08-27 ET 03:45-04:45). READ-ONLY PRECHECK. Nothing restarted, nothing
written to runtime, no orders, no confirmation file, **no claim that Calm has live evidence.**

### VERDICT
ready to observe the next live Calm window: **NO**
and until the scheduler restarts the state is **WORSE than before 5ZX**
orders_possible **FALSE** | blocking B1 + PAPER_SHADOW_EVIDENCE | order journal **ABSENT**

### THE FINDING
The running scheduler (PID 11788) started **2026-08-26 22:07:37 ET**. Every 5ZX file was written
**02:08 ET or later - four to five hours after**. A schedule is built once at boot and held in
memory. Its own log: **"Track 1 SHADOW slots registered: 70"**. The code declares 71. Across
every scheduler log this project has, `CALM_DECIDE` / `CALM_OBSERVE` appear **0 times**.

### AND DOING NOTHING IS NOW THE DANGEROUS OPTION - MEASURED
At 10:00 ET today the live scheduler fires `TRACK1_CALM_1000`. That id no longer exists, the
child refuses `unknown_slot`, and the refusal is raised **BEFORE `window_open`**:
    RAISED ShadowRefused: unknown_slot ... | **ledger files written: 0**
Yesterday Calm refused too, but refused INSIDE the ledger and left a row. Today it vanishes, and
an audit reads a vanished window as **"nobody looked"** - strictly worse, and exactly the shape
Stage 5Q-3 eliminated for splice refusals.
=> **restart before 09:32 ET.** Quiet gaps: 04:21-06:20, 06:21-08:20, 08:21-09:31.
   Missed is better than half-done: DECIDE absent + OBSERVE running = a refusal row saying
   there was no decision to observe, which is correct and is NOT evidence.

### ADJACENCY TO WATCH ON DAY ONE
DECIDE 09:32 fires **one minute after** `track1_maxhold_exit` 09:31 - the job that wrote the
book at 09:31:13 on 08-26 (the 5ZS corruption). Measured runtime 1-13s => **~47s clearance** at
the worst observed. Different client ids (safety 90, slot child 89) so no connection collision.

### CODE vs LIVE
built from real construction: **102** jobs / **71** slots, DECIDE+OBSERVE registered,
CALM_1000 absent. **All four true in the CODE, all four false in the live process.**

### CHECKED AGAINST PRODUCTION, NOT A FIXTURE
unsplit sleeve argv: LIVE vs NEW **IDENTICAL** (TRACK1_STRESS_1035).
`--allow-orders` across **205** logged Track 1 launches: **0**. Across all 71 slots: **0**.

### EVIDENCE - NOTHING CLAIMED
3 judgeable days of 5, Calm labels all `pre_shadow_intent_schema`, **0 Calm days counted**,
no day execution-proven. Two details that change what the next window means:
- 08-26 the route reached **PASS on 2 of 4 sleeves** (stress + swing); Calm was not one.
- Calm's 08-26 reason was `gate_refused: partial_coverage,decision_bar_absent` - **from a run
  BEFORE the 5ZU timing fix landed.** No live Calm window has ever run against 5ZU or 5ZX.
- all three judgeable days are FAIL days anyway.

### A GAP FOUND BY TRYING TO BREAK IT, AND CLOSED
Deleting the phase branch from the scheduler left **every test in the corpus green**. Slot table
knew about phases, gate knew about phases, **nothing asserted the launcher passes one** - the
5th time here a mechanism was built and its wiring left unproven.
Closed by **test_16**: fires the REAL registered jobs with `_run` replaced and reads the argv.
One test, 4 collapses caught RED: source flag removed / phase branch deleted / `--allow-orders`
smuggled in / a phase leaking onto the 3 unsplit sleeves.

### THE WARNING FOR THIS EXISTS AND `status` DOES NOT PRINT IT
`ops.py` has `describe_scheduler_state`, whose docstring names this precedent: *"21 backend
restarts read as full restarts while a scheduler from three days earlier kept running a cron
table that no longer matched the code."* It is called from **exactly one place - the restart
path**. `ops.py status` never calls it. The read-only health command is the one command that
does not say the in-memory schedule no longer matches the code. **Recorded, not fixed** (a
precheck must not change the instrument it is reading). Repair = one call.

### TWO REPAIRS THIS PRECHECK OWNS (neither loosened)
- **dashboard fact pin** - bidirectional by design; 5ZX added a row without declaring it and the
  pin caught exactly that. Declared, which also brings it under the per-row check.
- **argv extractor (5D)** - read the launcher's first arg only as a single list literal; the 5ZX
  narrowing made it a concatenation, so it reported "no launch call" - reading like the wiring
  was deleted rather than reshaped. Now flattens a join and reports BOTH branches of a
  conditional. A removed flag still disappears; mutations confirm.

### REGRESSION, SORTED BY CAUSE NOT BY NAME
  before 5ZX repairs  109 failed / 2460 passed
  after  5ZX repairs   99 failed / 2470 passed
  after  this precheck **95 failed / 2476 passed / 5 skipped = 2576 collected** (reconciles
  against collect-only). 4 failures went; **3 are repairs here**, the 4th is a browser tooltip
  assertion in a file untouched by this work - passes alone, counted as the corpus's order
  dependence, NOT credited. **Nothing went red** - checked by DIFFING the failure lists, not by
  comparing totals.
  buckets: **45 caused by the Calm slot split** (measured: re-run with the old slot table
  restored, 45 turned green) | **~50 pre-existing** (roster pins, legacy 61 vs pinned 60,
  absence proxies asserting the live runtime tree does not exist) | ~~3~~ **4 true 5ZX
  regressions - all repaired** (CORRECTED in Stage 5ZZ: a third copy of the argv extractor in
  the ops-startup suite failed with different wording, so grouping by reason string put it in
  the pre-existing bucket. It asserts NO ORDER FLAG can reach a Track 1 slot and had stopped
  running).
  Corpus noise: same set run twice gave 109 then 98 => **11 order-dependent tests**, ~10%.
  The 45 are **left red and listed**: count pins are the roster anti-pattern already on record,
  and the ones driving the old slot exercise 10:00 semantics that no longer exist.

### Files touched
NEW: scratch/track1_stage5zy_pre_live_calm_phase_check_20260827.{md,json}
MOD: scratch/test_track1_stage5zx_...py (+test_16), test_track1_dashboard_runtime_wiring (pin),
     test_track1_stage5d_shadow_live_wiring (argv extractor), pipeline doc, TASK.md
CODE: none. RUNTIME: none. RESTART: none.

### NEXT EVENT TO WATCH
1. **the restart**, in a quiet gap before 09:32 ET
2. **2026-08-27 09:32 ET - TRACK1_CALM_DECIDE_0932** (first run of either phase, ever)
3. 2026-08-27 10:02 ET - TRACK1_CALM_OBSERVE_1002
Success = a shadow_intent file for the session; DECIDE row with NO price; OBSERVE reference ==
the 10:00 open; day classifies `decision_judgeable`; **orders dir still absent**; and the book
still schema 2 + route-stamped right after (the max-hold sweep runs a minute earlier).

---

## Task: Stage 5ZX - Calm decides at 09:32 and writes it down; nothing sends
Status: DONE (2026-08-27 ET 02:00-03:40). IMPLEMENTATION of the 5ZW plan.
**No SEND, none built, none authorised.** No orders, no confirmation file, no --allow-orders,
no IBKRBroker, no placeOrder, nothing written to track1_runtime/orders/, NOTHING restarted,
no production runtime file edited by hand.

### VERDICT
two phases **BUILT AND WIRED** (driven end to end through the function the scheduler calls)
Calm evidence counts the **DECISION**, never an execution
orders_possible **FALSE** | blocking **B1 + PAPER_SHADOW_EVIDENCE** - unchanged, measured
strategy identity **UNCHANGED** | paper readiness **NOT_READY**

### THREE THINGS ONLY RUNNING IT COULD SHOW
1. **The Calm detector returns NOTHING when today has no 10:00 bar.** At 09:32 that is every
   day in history. A DECIDE slot calling the ordinary candidate path would report "no setup
   today" every morning **in good faith** - five clean weeks satisfying a counter and meaning
   nothing. => the rule split where it genuinely divides; the full detector is built **ON**
   the shared pre-entry half, not beside it.
2. **`sleeves_at()` is empty at BOTH 09:32 and 10:02** - Calm's window is the single instant
   10:00. Neither phase can use the candidate path. OBSERVE runs **no detector at all**: the
   setup was found half an hour earlier and written down.
3. **The first refusal row said "gate_refused" when the gate had PASSED** and the source
   refused. A reader would have gone to inspect a working gate. Rows now carry the real name.

### STRATEGY DID NOT MOVE - PROVEN, NOT ASSERTED
319 sessions | 84 set up | 235 not | **digest IDENTICAL before/after**
  a573a9e32e326b937a8350addff31b94ab74f6f31c7b489773bc9987f09203f5
The new pre-entry half independently picks the same 84. Params untouched (entry 10:00, stop
1.5xATR, digest 0d80b152...). Comparison is clock-independent by construction (same frame both
runs) - the e2e run deliberately uses the route's OWN loader, which converts UTC -> New York.

### SCHEDULER - MEASURED FROM REAL CONSTRUCTION, NOT COUNTED
                     slots | track1-only | legacy+track1
  before (1 calm)      70  |     101     |     130
  after  (2 phases)    71  |     **102** |     131
  TRACK1_CALM_DECIDE_0932 (09:32) + TRACK1_CALM_OBSERVE_1002 (10:02); neither on the entry
  instant. `--phase` travels in argv ALWAYS. **A typo REFUSES** rather than falling back to the
  sleeve rule - falling back would gate the decide half with the entry-half requirement and
  leave a record indistinguishable from a correct run.

### END TO END, REAL SESSION 2026-08-21
  DECIDE  @09:32  RECORDED ok  MES  ref -        stop -
  OBSERVE @10:02  RECORDED ok  MES  ref 7680.75  stop 7577.9196
  ref == the frame's real 10:00 open to the cent | 7680.75-7577.9196 = 102.83 = 1.5 x 68.55
  classify => **decision_judgeable**, and the words carry the limit
  wrote: shadow_intent + signals + ledger. **NO orders dir, no trade log, no book, no
  checkpoint** - asserted, not noticed.

### EVIDENCE GATE
new check `calm_decision_evidence`; counts decision_judgeable + no_setup; **does NOT count**
pre_schema / incomplete / unreadable. Carries `proves: decision_only` and `does_not_prove:
acceptance_fill_or_slippage` in every record, and **raises** if handed an execution label.
Report now names each day in words: all 3 current days read **missing** (they predate the
stream) - the honest answer, not a reader failure.

### TESTS
**20 pass** (15 cases + 5 mutations, one per named collapse). Two failures while writing worth
keeping: a count over RAW SOURCE read the function's own docstring as code (the 5ZP trap again
- the reader now strips docstrings); and the decide-row builder cannot even BE ASKED for a
price, so the refusal lives a layer down - the test now proves both doors.
Adjacent: realtime contract **26 pass**, dashboard backend **194 pass**.

### REGRESSION - CLASSIFIED BY MEASUREMENT, NOT ASSUMED
scratch/ full, before repairs: **109 failed / 2460 passed**. Re-run with the pre-stage slot
table restored via a probe conftest: **45 go green** => caused by the slot split (roster/count/
slot-id pins). After the repairs below: **99 failed / 2470 passed** (measured). The rest are
pre-existing (blocker-roster pins, legacy count 61 vs a pinned 60, absence proxies, date pins).
**Also found: 109 -> 98 between two runs of the same set = order dependence**, its own finding.
REPAIRED (not stale pins - real safety assertions whose SCOPE moved): 5ZU test_20 and 5ZV
test_7 counted `_bar_open_at` and `entry_conditions` inside ONE function; the causal path is
now two. Widened to both halves AND per-half - **3 mutations confirm red**, including one
where the total is still 2 but split 2/0, which a total-only count would pass. Plus a stale
`_resample` stub signature.

### FINDING RECORDED NOT FIXED
**Signal diagnostics have NEVER carried a params identity.** The reader guards on
`hasattr(track1_params, "params_hash")`; that module never had one. The real function is in
`route_params`, takes a full config (and refuses a partial one - good design this caller never
reaches). Every diagnostics row since carries `params_hash=""`, so two rows compare equal
because both are blank.

### LIVE RUNTIME DURING THE STAGE
book + checkpoint both moved **02:55:42 ET** = the NKD window closing, the route writing its
own state. Live runtime, NOT stage output. Book came through still schema 2, route-stamped, no
foreign keys, flat: the **FOURTH** window close the 5ZS repair has survived.

### Files touched
NEW: global_index/track1_shadow_intent.py,
     scratch/test_track1_stage5zx_calm_shadow_intent_20260827.py,
     scratch/track1_stage5zx_calm_shadow_intent_20260827.{md,json}
MOD: track1_calm_a.py (split, digest-proven identical), track1_slots.py (phase + 2 slots),
     track1_intraday.py (PHASE_REQUIREMENTS + requirement_for), track1_live_source.py
     (calm_pre_entry), run_live_day_track1.py (--phase, writer, isolation),
     run_scheduler.py (--phase in argv), track1_paper_readiness.py (calm check + lines),
     monitor/backend/track1_runtime_reader.py + dash/realtime/realtime.js (one row),
     scratch/test_...5zu/5zv/5q2 (scope repairs), pipeline doc, TASK.md
RUNTIME: none written by this stage.

### REMAINING BEFORE PAPER
1. **PAPER_SHADOW_EVIDENCE** - 3 judgeable days of 5, and **0 carry Calm evidence** (the
   phases have not run in production yet)
2. **B1** - no decision; its measurement expires 24h after it was taken
3. **the SEND wire - DOES NOT EXIST**, and this stage did not build it
4. machine sleep (operator)

---

## Task: Stage 5ZW - review the 5ZV correction, then plan Calm's pre-paper execution
Status: DONE (2026-08-27 ET 00:20-01:20). REVIEW + PLAN. **No order-send implementation and
none authorised.** No orders, no confirmation file, no IBKRBroker, NOTHING restarted, no
runtime file written, Calm entry time and backtest untouched.

### VERDICT
5ZV correction **ACCEPTED** | Calm contract still **TRADABLE Option A** (the 10:00 open)
shadow evidence: can count the **DECISION**; the fill is **paper-only**
paper readiness **NOT_READY** | orders_possible **FALSE**

### THE CORRECTION IS RIGHT - AND LOOSER THAN THE TRUTH
`disaster_stop(entry, atr) = entry - mult x atr`, read from source: the stop LEVEL needs the
entry. My 5ZV first draft put `planned_stop` before entry - shadow would record a price it
cannot compute, the same error as recording the reference price early. **ACCEPTED.**
**But "the stop is not known" is loose.** Measured, two entries + one ATR:
  entry 5000.00 -> stop 4982.00, distance 18.00 | entry 5123.75 -> stop 5105.75, distance 18.00
=> the stop **DISTANCE** is 1.5 x ATR and is entry-INDEPENDENT; the **dollar risk** is
distance x point_value x qty and cancels the entry out; `qty` is a fixed sleeve constant
(`SLEEVE_QTY`), not risk-derived. **ONLY THE STOP LEVEL WAITS FOR 10:00.**
Split: before = setup/instrument/direction/qty/**stop_rule**/**risk_inputs**/
entry_reference_time/intent | after = entry_reference_price + **planned_stop** |
never in shadow = fill_price/fill_time/realised_pnl/slippage

### REVIEW ALSO FOUND
- strategy UNCHANGED (entry = 10:00 open, asserted); nothing authorised; NoOrderBroker still
  unconditional
- **no runtime file touched by the edits.** The book + checkpoint moved 15:56:24 ET because the
  SWING window closed - and the book came through **still schema 2, route-stamped, no foreign
  keys**: the THIRD window close the 5ZS repair has survived.
- **the docs were NOT internally consistent**: the 5ZV md listed `planned_stop` before-entry in
  its code block and contradicted itself 5 lines later. Block + JSON + pipeline doc now aligned
  - the block is what a reader copies.
- tests: **22 passed** alone, **76 passed** with 5ZN. Repairs were to stale ROSTER and DATE
  pins, not to safety assertions.

### THE PLAN - two jobs, one new stream
MISSING: DECIDE ~09:32 (nothing computes the setup from the closed 09:30 bar) and OBSERVE
10:01+ (nothing records the 10:00 reference). SEND 10:00:00 missing **BY DESIGN**.
**Two jobs, not one expanded slot**: a slot spanning 09:32->10:01 holds a process and a client
id ACROSS the entry instant, and a crash anywhere in that half hour loses both halves. The
phases read different things and fail differently; one slot cannot report which broke.
  TRACK1_CALM_DECIDE_0932 + TRACK1_CALM_OBSERVE_1002 replace TRACK1_CALM_1000 (101 -> 102 jobs)
**New stream `global_index/track1_runtime/shadow_intent/`** - every existing stream already has
a reader that counts it (`shadow/` holds explanations; a reader there would count intents).

### WHY THE INTENT MUST NOT GO IN THE ORDER JOURNAL (not a preference)
**FOUR readers treat the EXISTENCE of `track1_runtime/orders/` as proof the route acted:**
`b1_book_repair.route_has_never_traded` (**refuses the book repair**), `track1_paper_callsite`
(guards the production root), `track1_report` (NOT_PRODUCED while absent), and the runbook
("stop and investigate"). A shadow intent there makes all four report a route that traded on a
day it sent nothing - **and blocks its own book repair.** Now pinned by tests BEFORE anyone
implements it.

### WHAT CHANGES LATER: one job, one swap, one promotion
SEND job at 10:00:00 reading the recorded intent (**reads NO bars** - that is what makes it
free of future data) | `UnbuiltPaperExecutor` -> a real executor, proven separately | the
shadow intent **PROMOTED** to an INTENDED row in the real journal - same fields, different
stream, and the promotion is the act that says this is no longer a rehearsal.
DECIDE/OBSERVE times and the entry reference do NOT change - that is the point of building now.

### A FINDING RECORDED NOT FIXED
`ORDERS_DIR` is defined **independently in 3 modules** (track1_order_journal, b1_book_repair,
track1_report) while a 4th uses the shared constant. Three definitions of one path drift
silently and the readers proving "the route has not traded" would look in different places.
A test asserts they still agree - fails the day they stop, the only way anyone would find out.

### Tests: 15 (scratch/test_track1_stage5zw_calm_prepaper_execution_20260827.py)
One failed while being written for a reason worth keeping: it demanded each reader contain the
orders-dir **literal**, and `track1_paper_callsite` references the shared **constant** - the
module doing it the BETTER way. Now accepts either, and records the duplication as the finding.
The blocker assertion is a **PROPERTY**, not a roster (the roster moved twice in two days).

### Files touched
NEW: scratch/test_track1_stage5zw_calm_prepaper_execution_20260827.py,
     scratch/track1_stage5zw_calm_prepaper_execution_plan_20260827.{md,json}
MOD (docs only): scratch/track1_stage5zv_...{md,json}, pipeline doc, TASK.md
CODE: none. RUNTIME: none.

### REMAINING BEFORE PAPER
1. B1 - decision + a fresh measurement (the current record expires 24h after 11:34 ET)
2. PAPER_SHADOW_EVIDENCE - **3 of 5**; Calm contributes none until DECIDE/OBSERVE exist
3. machine sleep (operator)
4. **the SEND wire** - does not exist

---

## Task: Stage 5ZV - Calm shadow/paper execution identity: tradable, not just judgeable
Status: DONE (opened 2026-08-26, closed 2026-08-27 00:06 ET). No order send wired. NOTHING
restarted. No runtime evidence written. Entry price definition UNCHANGED. Splice guard untouched.

### VERDICT
Calm contract **TRADABLE** (Option A, the 10:00 open) | shadow/paper **MATCH** under the
contract declared here (was a **MISMATCH** under the 10:01 reading 5ZU left open)
backtest rerun **NOT required** | Calm counts toward evidence **for the DECISION half only**
orders_possible **FALSE**

### THE MEASUREMENT THAT DECIDES IT
Not "when can the route SEE the 10:00 bar" (5ZU answered that) but **how early is the setup
known**. Rebuilt all 421 frozen setups from a frame **TRUNCATED at 09:30**: **407/421
reproduce**. The other 14 = 5 sessions missing their own 09:30 bar + 9 the rule no longer
selects on today's re-adjusted series. Neither is about truncation.
=> the rule reads the prior RTH session + today's 09:30 OPEN and NOTHING else. That OPEN exists
at 09:30:00; a CLOSED 1-min bar carries it at 09:31:00. Entry is 10:00.
**29 MINUTES OF SLACK** - that is what makes the original contract tradable.

### WHY 5ZU WAS NOT ENOUGH
An order sent at 10:01 cannot fill at an open that happened a minute earlier. A shadow row
claiming it claims a fill paper can NEVER achieve. **Judgeable != tradable.**

### WHAT MOVING THE ENTRY WOULD COST (416 rows, one consistent read, on DIFFERENCES)
| entry | total | vs 10:00 | stdev | sign flips |
| **10:00** (record) | $14,776 | - | - | - |
| 10:01 | $13,606 | **-$1,170 (-7.9%)** | $20.6 | 18/416 (4.3%) |
| 10:05 | $14,726 | -$51 (-0.3%) | **$36.7** | **29/416 (7.0%)** |
**Read the 10:05 row carefully**: total barely moves, per-trade spread NEARLY DOUBLES, 29
trades flip sign. **The aggregate HIDES the change rather than showing there is none.** A
number that looks like "no difference" is the one to distrust.

### THE STRUCTURE (answer 3) - and the machinery already existed
DECIDE ~09:32 (closed 09:30 bar; writes INTENDED to the journal; reads nothing after 09:30) ->
SEND 10:00:00 (paper only; acts on the journal, reads NO bars) ->
OBSERVE 10:01+ (records what the 10:00 OPEN was; in paper it is the slippage denominator).
**Stage 5V's journal already separates INTENDED from SUBMITTED.** Nothing invented.
SEND is deliberately NOT built - constraints forbid it and the route still builds NoOrderBroker.

### WHAT SHADOW MAY SAY
before entry: setup/instrument/direction/qty/stop_rule/risk_inputs/entry_reference_time/intent
after reference: entry_reference_price/planned_stop
after the reference bar closes: entry_reference_price
**never in shadow: fill_price, fill_time, realised_pnl, slippage** - shadow sent nothing.

### THE GATE MOVED WHILE THIS STAGE RAN - I reported 3 blockers; **it is 2 now**
- **REGIME_LABEL_VERIFICATION RELEASED - its FIRST PASS EVER.** Two records today: 17:47 UTC
  (13:45 ET pre-flight) and 20:20 UTC (16:20 ET refresh), both "1761 label(s) compared through
  2024-12-31, none changed". 5ZL built that gate; this is the first time it said yes.
- PAPER_SHADOW_EVIDENCE: 2 -> **3 of 5** judgeable days
- legacy_broker_flat still PASS on a NEWER record: 2026-08-26T15:34:28Z = 11:34 ET, the same
  minute the book repair was applied - the operator re-recorded B1, as the 5ZS runbook asked.

### TWO TESTS, AND ONLY ONE WAS WRONG
- `test_ledger_matches_the_registry_exactly` compares a frozen file against `as_ledger()`,
  which **embeds LIVE measurements** - it drifted again within hours of the 5ZR regeneration.
  **A parity test that goes red on its own schedule is one people regenerate past without
  reading.** Static half now compared exactly; live half checked for SHAPE. Second test added.
- `test_the_preflight_record_still_holds_..._seven_days` was a **TIME BOMB and it went off
  correctly**: 5ZM put it up after the 5ZL incident so no test of mine could fabricate today's
  clearance. The real 13:45 pre-flight has now run - 2026-08-26 present, 2026-08-17 rolled off.
  **The guard did its job for four stages and expired.** Should assert the PROPERTY, not a date
  list. Left for whoever next touches 5ZN.

### Tests: 20. Mutations **9/9 RED**
One was still green first time: `test_5`'s fixture used `order_sent_at=09:59`, which ALSO breaks
the send-equals-reference rule, so `self_check()` stayed non-empty with the ordering check
disabled and the test passed for a rule it was not testing. **A bare "is non-empty" over a
five-rule validator cannot say which rule fired.** Now trips exactly one and asserts `len==1`.

### Files touched
NEW: scratch/test_track1_stage5zv_calm_execution_identity_20260826.py,
     scratch/track1_stage5zv_calm_shadow_paper_execution_identity_20260826.{md,json}
MOD: global_index/track1_calm_a.py (CalmExecutionContract + SHADOW_MAY_RECORD +
     PAPER_ONLY_EVIDENCE), scratch/test_track1_stage3b_blockers_20260822.py,
     scratch/track1_blocking_ledger_20260822.json, pipeline doc, TASK.md

### REMAINING BEFORE PAPER
1. B1 - operator decision + fresh measurement
2. PAPER_SHADOW_EVIDENCE - **3 of 5**; Calm cannot contribute until its slot moves to 10:01/02
3. ~~REGIME_LABEL_VERIFICATION~~ **DONE 2026-08-26**
4. machine sleep (operator)
5. **the order path** - the SEND phase does not exist (code, unwritten)

---

## Task: Stage 5ZU - Calm A timing identity: the gate asked for a bar that cannot exist
Status: DONE (2026-08-26 ET 11:45-13:10). NOTHING restarted. No broker connection. No runtime
evidence written. Splice guard untouched. Entry price definition UNCHANGED and asserted.

### VERDICT
backtest contract **CONFIRMED** (421/421) | live gate mismatch **CONFIRMED** (4 minutes/day)
fix applied **YES** (gate AND call site) | strategy changed **NO** | splice guard **unchanged**
Calm judgeable? **YES in the gate - NOT YET in the schedule** | orders_possible **FALSE**

### ONE NUMBER CARRIES THE STAGE
On all 421 rows `entry_time - signal_time` takes **exactly ONE value: 30 minutes**. The
decision is fixed half an hour before the bar the live gate was waiting for. The rule reads
the prior RTH session and today's 09:30 open. The 10:00 bar contributes ONE thing: the OPEN.

### THE CONTRADICTION
decide_to 10:00 + 60s grace -> deadline **10:01:00**; a closed 10:00 **5-minute** bar first
exists at **10:05:00**. Four minutes apart, every day. Calm was the **ONLY** sleeve with
`decision_bar == decide_from` - the bar it waited to close was the instant it could first look.
Stress escapes (today_to 10:30 < decide_from 10:35); swing/NKD escaped via 5V-1's
`today_to_follows_now`. Calm was left out of that fix **on purpose** - right about the PRICE,
wrong about the DECISION.

### THE FIX - two names where one did both jobs
`required_context_through=09:55` (what the DECISION reads) + `required_entry_quote_time=10:00`
(the bar whose OPEN is the fill reference), checked against the **MINUTE** index it is read
from. `decision_bar=None` for Calm. New codes `entry_quote_absent` / `entry_quote_unverified`
(the latter NEVER a pass). Grace 60s -> **180s**: an OBSERVATION change - a 1-minute bar
stamped 10:00 closes at 10:01:00, so 60s put the deadline ON the closing instant.

### THE GATE CHANGE ALONE DID NOTHING
The slot passed only the resampled 5m frame, so every Calm slot would have refused
`entry_quote_unverified` instead of `decision_bar_absent` - **a different refusal, not a fix.**
The regression caught it (a 5E slot test stopped reaching `decided`). The 1-minute frame was
already in scope 3 lines above the call. **A guard added and not wired: the 4th time.**

### PARTIAL-BAR CONSTRAINT HOLDS BY CONSTRUCTION
Measured 10:00:19 today: MNQ's frame already had a 19-second-old 10:00 bar, MES's had none.
The context span stops at 09:55, so a 10:00 bar is OUTSIDE what the decision reads - proved by
verdict EQUALITY (adding a partial bar with high 99 / low -99 changes nothing).

### WHAT IT DOES NOT FIX - the honest part
**Calm will still refuse tomorrow at 10:00**: the slot is dispatched at 10:00:00 and the quote
closes at 10:01:00. It now refuses for a REAL reason instead of an impossible one.
**Remaining: dispatch the Calm slot at 10:01/10:02** - a cron edit + restart, RECOMMENDED not
applied. Entry price unchanged, so it is an observation-time change, not a strategy change.
Until then PAPER_SHADOW_EVIDENCE cannot count a Calm PASS.

### A MEASUREMENT ERROR OF MINE
First pass used `_naive()` (strips tz, does not convert) on a **UTC** parquet - 420/421
mismatched. The tell was not the count: the file returned `9184.872880047082` where the record
held `8753`. **A price that cannot be a tick is a fault in the measurement.**

### AND A FINDING ABOUT THE RECORD
Older rows' prices are NOT reproducible from today's parquet **by design** - back-adjusted
continuous series. SANITY_2026 **28/28 exact**; OOS_2025 0/44 (max 535.75); IS_2018_2024 0/349
(max 1548.43). Adjustment not a different bar, three ways: offsets monotone in age (~50 levels);
`exit-entry` identical on **395/416**; the offset-INVARIANT feature agrees far more often.

### Tests: 33. Mutations **11/11 RED** incl. all five the stage named
### REGRESSION BISECT: full scratch sweep 2461 passed / 48 failed
Reverted the two SOURCE edits in a subprocess and re-ran the 20 affected suites:
  with 5ZU **46** distinct failures | without **33** | **CAUSED BY 5ZU: 13** — all 13 FIXED.
- **the grace group (9)**: 5ZB pinned `grace == 60` on EVERY sleeve and that 61s/120s late is
  refused. Calm's is now 180s on purpose. Rewritten to read the grace **per sleeve from the
  requirement**, and to assert the odd one out is the sleeve with an entry quote to wait for -
  **stronger** than the uniform number, which was pinning a coincidence.
- **the calm gate group (4)**: 4B/4C/5ZA called validate for Calm without saying where the
  quote comes from -> UNVERIFIED. Each now offers the minute index. 4B's second half asserted
  `decision_bar_absent`, a code Calm no longer emits; it now asserts the SPAN refusal, which is
  the same claim in the contract's terms.
- **a helper of mine overflowed**: `_slot_now(slot, seconds=181)` formatted the seconds field
  and produced `10:00:181` - the test died on a parse error, not an assertion. Fixed with a
  Timedelta. Recorded because it LOOKED like a contract problem and was not.
**FINAL after all repairs: 2476 passed / 35 failed** (was 2461/48). **None of the 13 remain.**
35 vs the bisected 33 because the full sweep runs 67 suites vs the bisect's 20 and this repo
has measured order-dependent failures before (15 in the 5ZQ sweep).
Spot-checked the one that touches the book: `test_8c_persisting_the_book...` is an ABSENCE
PROXY asserting `live_positions.track1.json` does not exist - the live system wrote it at
12:30:25 today. Stale since **5ZN**, not 5ZS and not 5ZU.
5 older tests UPDATED not weakened; one got STRONGER (3B now separates "quote index not
offered" from "offered and absent"); one added. Regression 307 passed / 1 failed - the one is
a roster pin measured PRE-EXISTING in the 5ZQ bisect.

### STAGE 5ZT CLOSED HERE (its deliverables were never written - events were in the future)
**12:30:25 ET the stress window closed and wrote BOTH book and checkpoint.** Book still
schema 2 / route track1_candidate - **the repaired envelope survived a real window close.**
Checkpoint written for the first time since 02:55. Zero carry-forward refusals. Legacy
untouched at 09:31:11. Orders impossible throughout.

### Files touched
NEW: scratch/test_track1_stage5zu_calm_timing_identity_20260826.py,
     scratch/track1_stage5zu_calm_timing_identity_20260826.{md,json}
MOD: global_index/track1_intraday.py, global_index/run_live_day_track1.py,
     scratch/test_track1_stage5v1_*, scratch/test_track1_stage3b_*,
     scratch/test_track1_stage4_production_clean_*, pipeline doc, TASK.md

### REMAINING BLOCKERS AFTER 5ZU (unchanged - no gate touched)
1. B1 - operator decision + fresh measurement
2. PAPER_SHADOW_EVIDENCE - 5 clean days; **Calm cannot contribute one until its slot moves**
3. REGIME_LABEL_VERIFICATION - first PASS
not gates: machine sleep (operator); **the order path does not exist** (code, unwritten)

---

## Task: Stage 5ZS - Track 1 book carry-forward: safety jobs stop writing it in legacy shape
Status: DONE (2026-08-26 ET 11:00-11:40). NOTHING restarted. NO broker connection.
**NO runtime file written** - the corrupt book was left as found; its repair is a DRY RUN.

### VERDICT
live book corrupted? **YES** | repaired? **DRY-RUN ONLY** (prompt did not say apply)
safety jobs fixed? **YES** (3 layers, 15/15 mutations red) | legacy unchanged? **YES** byte-for-byte
runtime files touched? **NONE** | orders_possible **FALSE**, 3 blockers unchanged
next window? **RUNS, but will REFUSE to write evidence until repaired - that is the fix working**

### THE EVENT
`TRACK1_MAX_HOLD_EXIT` 09:31:00 -> completed 09:31:13 ET = **the book's mtime to the second**.
argv was FULLY route-aware (own book/stop/lock/client-id 90/trade-log/`--route`) - 5ZG's
routing worked perfectly. **Nine fields dropped, schema 2->1, and a legacy breaker INVENTED**
(peak_equity 50000.0, last_broker_equity 996881.46). `positions: []` before and after - which
is exactly why it was quiet, and why it would NOT be on the first day the route holds anything.
**Today was the FIRST opportunity**: the schema-2 book was born 02:55 (5ZN); MAX_HOLD runs 09:31.

### ROOT CAUSE - a fail-open at BOTH ends
- writer `FuturesRunner._persist_state` builds `{schema_version:1, positions, breaker}` always
- loader hits `sv not in (0,1)` and logs **"proceeding anyway"**, finds no `breaker`, so every
  breaker field keeps its DEFAULT - and the writer persists those defaults.
**Same defect in `run_stop_repair`** - LATENT only (nothing to change at 02:20/04:20/06:20/08:20).

### THREE LAYERS
1. **writer** preserves the envelope it read, gated on `route is not None` (5ZG's switch).
2. **carry-forward**: `route is None` used to PASS - that is how the file was accepted in
   silence; and `dict(prev)` copied every key. Now route+schema must match, only declared
   fields carried, missing declared fields return at their default (never absent).
3. **`safety_book.py`** - the book's version of 5ZG's trade-log contract, placed BEFORE the
   positions-exists early return (that return fires every run in shadow).
   **NARROWED ONCE on purpose**: the first draft demanded the canonical filename for ANY routed
   run - not the hazard; it broke 4 5ZG tests using a temp book. **A false positive is not a
   caught hazard.** Rule now names the hazard (the legacy book); a mutation pins the narrowing.

### REPAIR - recovers NOTHING and says so
The checkpoint carries per-instrument resume state and **no book envelope**, so the 9 lost
fields have no source on disk. `b1_book_repair` rebuilds at the route's defaults + carries
positions, and PROVES the route never traded first (trade log 0 rows, orders dir absent).
Refuses over an open position or a traded route - that would be a guess about money.

### COST TODAY: the 12:30 stress close will REFUSE and read as a failed window
That is cheaper and VISIBLE vs the alternative (corruption propagating into a well-formed book
carrying a foreign breaker). **No restart needed** - every slot/safety job is its own process.

### A GAP THIS STAGE ALSO CLOSED
**B1 called the corrupt book FLAT** - `read_book` asks only "how many positions", and a
legacy-shaped file over the route's path still carries `positions: []`. Now `read_track1_book`
checks the envelope; B1 reports UNKNOWN. `ops status` still prints PASS **correctly** - it
reads the 06:15 RECORD, true at 06:15; the damage came at 09:31.

### Tests: 42. Mutations **15/15 RED** incl. the four named by the stage
Fixture copied FIELD-FOR-FIELD off the live file. **Two of my tests proved nothing:**
the loader stash had NO test (writer tests inject the attribute), and the narrowing test used a
path that did not exist so `dest.exists()` short-circuited. Both rewritten.
### Regression: **658 passed, 0 failed, 1 skipped**

### Files touched
NEW: global_index/safety_book.py, global_index/b1_book_repair.py,
     scratch/test_track1_stage5zs_book_carry_forward_20260826.py,
     scratch/track1_stage5zs_book_carry_forward_safety_isolation_20260826.{md,json}
MOD: run_live_day_track1.py, runner.py, track1_slots.py, run_maxhold_exit.py,
     run_stop_repair.py, track1_b1.py, b1_audit.py, pipeline doc, TASK.md
RUNTIME TOUCHED: **none**

### REMAINING BLOCKERS AFTER 5ZS (unchanged - this stage touched no gate)
1. B1_broker_account_or_legacy_retirement - operator decision + fresh measurement
2. PAPER_SHADOW_EVIDENCE - 5 clean judgeable days (today: 2, both FAIL)
3. REGIME_LABEL_VERIFICATION - first PASS
plus, not gates: machine sleep (operator); **the order path does not exist** (code, unwritten)
plus NEW, time-bound: repair the book before 12:30 ET or the stress close fails
```
python -m global_index.b1_book_repair            # look
python -m global_index.b1_book_repair --apply    # repair
python -m global_index.b1_audit --broker ibkr --record
```

---

## Task: Stage 5ZR - record the B1 operator decision safely, without enabling orders
Status: DONE (2026-08-26 ET 08:20-09:00). **NO confirmation file created.** No broker
connection opened at all. NOTHING restarted. No runtime file / book / trade log / checkpoint
/ audit record touched. Legacy drain safety left scheduled. orders_possible FALSE, 3 blockers.

### The ten answers
1. recorded or templated? **TEMPLATED ONLY (Option 1)** - reason MEASURED, not cautious
2. which decision? **NEITHER is true today**   3. measurement: the 06:15:51 ET PASS, 2.2h old
4. B1 **PENDING** (measured half passes, decided half empty)
5. PAPER_SHADOW_EVIDENCE + REGIME_LABEL_VERIFICATION **both still blocking**
6. orders_possible **FALSE** in every simulated confirmation shape
7. broker/order action **NONE**   8. runtime file changed **NO**
9. legacy drain **STILL SCHEDULED (11 jobs)**   10. 5 items remain; #5 is the missing order path

### WHY OPTION 1 - and NOT "unsure the code is safe"
Simulated every shape in memory, writing nothing: `nothing` / `legacy_retired_confirmed` /
`separate_account_confirmed` / `decision+waiver` -> **orders_possible=False in all four**. The
mechanism IS safe. The refusal is on the MERITS: **neither decision is TRUE today.**

**LEGACY IS DORMANT, NOT RETIRED** - measured by building the scheduler both ways:
| | track1-only-shadow | default mode |
| total jobs | 101 | 61 |
| **legacy ENTRY jobs** | **0** | **45** |
| legacy safety (drain) | 11 | 12 |
**The difference is ONE command-line flag.** A restart without `--track1-only-shadow` puts 45
legacy entry jobs back and a recorded `legacy_retired_confirmed` would go on reading as TRUE.
Retiring legacy is the runbook's ordered procedure (section 3) - not run, drain still on.
**SEPARATE ACCOUNT**: there is ONE account (equity 996,883). No second one has ever been
observed, so the measurement cannot corroborate that decision at all.
And the runbook says the file is written by a person, never by a script - including this one.

### STRUCTURAL PROOF a B1 decision reaches B1 and stops
PAPER_SHADOW_EVIDENCE / REGIME_LABEL_VERIFICATION / LIVE_FRAME_ADAPTER are MEASURED_GATEs with
`released_by == ()`, and `self_check` REFUSES a MEASURED_GATE any flag could open.

### BUILT
- `global_index/track1_b1_decision.py` - read-only previewer: what would open, what stays
  shut, orders_possible, the live measurement + expiry, and whether the RUNNING scheduler can
  still open a legacy position (three-valued: none/present/**unknown**).
  **Writes nothing** - asserted by watching every file opened for writing, again by AST, and
  it never names the live confirmation path.
- `scratch/track1_b1_decision_template_20260826.json` - **inert by construction**: a verbatim
  copy refuses for TWO independent reasons (unknown underscore keys; empty confirmed_by).
- `track1_paper_readiness` - its closing paragraph said B1 was released by "a confirmation
  file". True until 5ZQ, **quietly wrong since**. Now reports B1 as TWO HALVES and states that
  no gate builds an order path. Evidence half unchanged: **2 judgeable days, both FAIL.**

### TWO OF MY OWN TESTS PROVED NOTHING - the sweep caught both
- *template refuses for >1 reason*: it stripped the underscore keys itself, so removing that
  guard from the template left it GREEN. **A test that performs the mutation it is meant to
  detect cannot detect it.** Now works by ABLATION (each defence removed in turn) + a control.
- *legacy capability has three values*: AST-inventoried the constants returned ANYWHERE.
  Changing the no-scheduler branch UNKNOWN->NONE left all three present (the except handler
  still returned UNKNOWN), so the function began claiming "legacy cannot enter" about a
  scheduler it could not see. Now the branch is EXERCISED, not inventoried.
Same lesson twice: **a test that lists what exists is not a test of what happens.**

### Tests: 30. Mutations **12/12 RED** (2 were STILL GREEN on the first sweep -> rewritten)

### REGRESSION uncovered a LEDGER that had gone quiet
Targeted 407/4 (the 4 = known 5C slot-count family, pre-existing, measured in 5ZQ).
**All 33 suites touching the gate registry / readiness: 1196 passed, 30 failed.** THREE of
those are in the LEDGER suites, which **the 5ZQ bisect never covered** - they were not among
the 14 it ran.
**ONE IS MINE, and the test was right**: `test_ledger_releasing_every_gate_would_open_the_route`
asserts the blocker set is satisfiable and NOT by signatures alone - hold each measurement shut
in turn, exactly the dependent gates must refuse. **5ZQ introduced a SECOND KIND of
measurement** (`also_requires_measurement` is an AND; `released_by_measurement` is an OR) and
the loop only knew the first, so `legacy_broker_flat` read as "releases no order-blocking gate"
- true, and beside the point. Both kinds covered now; for an AND-measurement the claim is
STRONGER (the gate refuses with every signature already granted).
**And it gained an assertion it never had**: granting ONLY the waiver flags with every
measurement held shut must open NOTHING. The escape hatch must not become a way in.
**TWO WERE OLDER**: the JSON ledger listed 2 blockers where the registry has 3, and the MD
ledger **did not mention REGIME_LABEL_VERIFICATION at all** - a gate the operator is currently
held by, missing from the page they read to find out what holds them. Both stale since 5ZL.
Repaired: JSON regenerated (its own failure message says "regenerate it rather than editing
it"); MD given the missing gate from the registry's own text + a 5ZQ amendment section.
**PROCESS GAP LEFT NAMED**: `as_ledger()` has **NO WRITER anywhere in the repo**. "Generated
from the registry" is true as intent, manual in practice - which is exactly how it went a whole
stage unregenerated. Belongs in whatever stage next touches the registry.
**AFTER THE FIXES: 1201 passed, 25 failed** (was 30). **FIVE went green, all five ledger-parity**
(3 in 3B, 1 in 4B, 1 in 4C - the last two were reading the same record).
**25 still red and NOT mine.** Four suites (4B/4C/5AB/5B) were never covered by the 5ZQ bisect,
so they were checked INDIVIDUALLY here: same two families. The one that could have been mine -
`test_the_live_frame_gate_cannot_be_opened_by_a_signature` - expects the MEASURED_GATE set to
be one gate; it is three because 5S and 5ZL each added one. **`legacy_broker_flat` is not in
that set at all**: it is an AND-requirement on a DECISION gate, not a measured gate.

### THE DECISION HAS CHANGED SHAPE
No longer "sign the file". It is now: **decide which route owns the login, and MAKE THAT TRUE**
- either run the switch-over procedure, or fund a second account. The file records the
decision; it does not perform it.

### Files touched
NEW: global_index/track1_b1_decision.py,
     scratch/track1_b1_decision_template_20260826.json,
     scratch/test_track1_stage5zr_b1_decision_20260826.py,
     scratch/track1_stage5zr_b1_operator_decision_20260826.{md,json}
MOD: global_index/track1_paper_readiness.py,
     docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md
NOT CREATED: track1_go_live_confirmation.json (still absent, deliberately)

### OPERATOR
```
python -m global_index.track1_b1_decision scratch\track1_b1_decision_template_20260826.json
python -m global_index.b1_audit --broker ibkr --record   # measurement expires 24h after 10:15 UTC
```

---

## Task: Stage 5ZQ - legacy flat / B1 closure audit before Track 1 paper
Status: DONE (2026-08-26 ET 06:00-07:00). NOTHING RESTARTED. No position closed, no order
cancelled or modified, no account state written. NO book / trade log / checkpoint / audit
record touched. Legacy drain safety left scheduled. orders_possible still FALSE, 3 blockers.

### The eleven answers
1. legacy file book flat? **YES** `positions: []`   2. broker flat? **YES** 0 pos / 0 orders
3. orphan orders? **NO** - and impossible: there are no orders at all
4. Track 1 book flat? **YES** `positions: []`, cut 02:55 ET today
5. B1 closable by measurement? **its measured half PASSES; the gate stays shut, correctly**
6. what remains for B1? the operator's recorded decision + a PASS newer than 24h
7. broker/order action? **NONE** - three reads (positions, working orders, equity)
8. runtime file changed? **ONE, by design**: global_index/track1_b1/track1_b1_20260826.jsonl
9. orders impossible? **YES**   10. next window READY? **YES** sched 18780 untouched, calm 10:00 ET
11. before paper: 5 items, and #5 is **the order path does not exist**

### THE ACCOUNT, ASKED - first time ever
06:15:51 ET, IBKRBroker read-only client id 97 (1 legacy / 90 t1-safety / 99 dashboard):
**0 positions, 0 working orders (reqAllOpenOrders, ALL clients), equity 996,883.65.**
Corroborated by the dashboard reader on client id 99: same 0/0, equity 996,883.66 - **two
client ids, two code paths, ten cents apart.**
**Why a SHARED account can answer**: attribution only matters when something is NONZERO.
Zero positions + zero orders needs no attribution. That is the one shape of B1 a shared
login can answer, and the measurement is built on it: anything nonzero is FAIL/UNKNOWN.

### THE DASHBOARD'S 0/0 WAS NEVER EVIDENCE
Both collectors in `ibkr_reader` build their list inside try/except, log a warning, leave the
list **EMPTY**, and the payload publishes `connected: true, error: null`. So empty meant
EITHER "holds nothing" OR "the call raised" - **fail-open, on the exact question B1 asks**.
No backend log on disk, so the warnings are not recoverable either.
Fixed: `positions_ok` / `orders_ok` / per-section error; both start False; both CLEARED on
disconnect so a stale True cannot keep testifying. A payload without the flags reads UNKNOWN.
**NOT LIVE** - needs a backend restart. Until then the audit needs `--broker ibkr`.

### `IBKRBroker.get_open_orders()` HAD ZERO CALLERS
Written in 5X with the honest contract (None-not-[], unfiltered by clientId because another
client's order is still exposure on this account). The honest reader sat beside the fail-open
one for many stages and **nothing ever asked it anything.** Now it has one caller.

### GATE: B1 needs a DECISION **AND** A PROOF
was: `released = legacy_retired_confirmed OR separate_account_confirmed` (a signature alone)
now: `released = signed AND (measurement passes OR explicit waiver)` - **strictly tighter**
New `Blocker.also_requires_measurement` (an AND, vs `released_by_measurement`'s OR) +
`waiver_flag`. `b1_measurement_waived` releases NOTHING alone and is REFUSED without a `note`.
Every other blocker has both fields empty (asserted). self_check clean, 2 new rules added.
**The measurement deliberately CANNOT close B1 alone**: flat at 06:15 says nothing about 14:05.

### THE LEGACY TRADE LOG CANNOT PROVE FLATNESS
28 rows: 18 OPEN / 10 CLOSE / **8 net unmatched** - but 6 of those 8 are MES SHORT
entry_day 2026-08-07 at 19:10/19:20/19:30/19:40/19:50/20:01 UTC, **every one with order_id
null and perm_id null**. Six identical opens on a 10-minute cadence is a job re-logging, not
six fills. Log stops 2026-08-11; book last written 2026-08-24. **Book + broker are the
authorities.** Same shape as the known exit-path gap (3 of 5 close paths write no row).

### A RUNBOOK CHECK THAT CAN NEVER FIRE
SHADOW_WINDOW_RUNBOOK 2.7 forbids `global_index/live_positions.track1.json`; the code writes
`live_positions.track1.json` at the ROOT. And it is stale in substance: since 5ZN the book
carries cross-day state and **is expected** in shadow. The test is `positions: []`, not absence.

### TWO THINGS CAUGHT IN MY OWN WORK
- **an unreachable branch**: `measure()` had a `position_without_stop` result that could never
  return - any nonzero position fails on the line above. A branch that cannot fire reads as a
  check that runs. Status removed; detection kept as a FINDING where it is reachable.
- **the live-frame gate closed on me, and was RIGHT**: the tool was first
  `global_index/track1_b1_audit.py`; that gate scans every `global_index/track1_*.py` for
  IBKRBroker and demands the splice guard. **A 4th blocker appeared.** The rule was NOT
  softened - the file was in the wrong category (it never asks for a bar; `run_stop_repair`
  and `run_maxhold_exit` connect to IBKR outside that namespace for the same reason). Moved to
  `global_index/b1_audit.py`. A test pins BOTH directions so the move cannot read as evasion.

### Tests: 46 (structured payloads + AST, no prose greps). Mutations **11/11 RED**
Harness checks pytest actually COLLECTED tests first - exit 5 means nothing ran, and reading
that as red is how a sweep certifies itself (that happened earlier today and was caught).

### REGRESSION: targeted 447/0. FULL scratch sweep **2359 passed / 43 failed**
Same 14 suites run ALONE give 28 -> **15 of the 43 are ORDER-DEPENDENT** (cross-suite state
leakage; a separate problem, not chased here).
**BISECT (measured, not argued)**: every 5ZQ edit reverted + both new modules moved aside in a
subprocess, same 14 suites re-run, everything restored and digest-verified.
  with 5ZQ 27 distinct failures | without 5ZQ 26 | **CAUSED BY THIS STAGE: 1**
The one: `test_41_get_open_orders_is_CALLED_by_nothing_in_the_legacy_route`. Its NAME says
nothing in the LEGACY ROUTE calls it; its ASSERTION said nothing ANYWHERE does - a stronger
claim than its own intent, and **the reason the method sat uncalled for several stages.** Now
names its allowed callers + a second test requires the allowed caller to ACTUALLY call it.

### 26 TESTS WERE ALREADY RED AND NO REGRESSION SET INCLUDED THEM
The 06:03 ET baseline proves the two biggest causes independently: three blockers, and
`live_positions.track1.json` already on disk from the 02:55 NKD close. Both predate my edits.
| category | pins | stale since |
| roster pins | the EXACT blocker list (one, then two) | 5S, then 5ZL |
| absence proxies | `live_positions.track1.json` must not exist | 5ZN gave the route a book |
| slot-count pins | 25 Track 1 slots, "the two windows" | 5N gave it all four sleeves |
| substring-over-prose | *"a Track 1 slot asks for orders"* | it never did |
**None of the roster-pinning tests is ABOUT the roster** - that is why one new blocker breaks
a dozen unrelated suites, and it will keep happening.
2 in 5ZO and 3 in the freshness suite were **NOT traced** - naming a cause would be a guess.
**REPAIRED HERE (2)**: the false *"a Track 1 slot asks for orders"* alarm - it matched a
COMMENT reading *"Still no --allow-orders"*, the comment asserting the absence read as the
presence; and one roster pin, rewritten to assert its own claim instead of the roster.
**LEFT (24)**: a stage of its own. That stage should also put `scratch/` in a regression set
somebody runs - the measurable fact is not that these broke, it is that nothing noticed.

### A STALE PIN IN A SUITE NO REGRESSION SET INCLUDED
`test_track1_dashboard_runtime_wiring_20260824.py` pinned `t1Fact('Blocking gate')`; the panel
renders `Blocking gates`. **Which stage renamed it CANNOT BE DATED** - the whole panel is
uncommitted, so there is no earlier revision. Not guessed at. What IS measurable: this suite
was in no stage's regression set. Label corrected AND the list COMPLETED - it pinned 10 of 13
facts, so three could have vanished unnoticed. A second test checks the other direction.

### Files touched
NEW: global_index/track1_b1.py, global_index/b1_audit.py,
     scratch/test_track1_stage5zq_legacy_flat_b1_20260826.py,
     scratch/track1_stage5zq_legacy_flat_b1_audit_20260826.{md,json}
MOD: global_index/track1_gates.py, monitor/backend/ibkr_reader.py, monitor/backend/app.py,
     monitor/ops.py, scratch/test_track1_dashboard_runtime_wiring_20260824.py,
     docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md
EVIDENCE WRITTEN: global_index/track1_b1/track1_b1_20260826.jsonl (by --record, by design)

### OPERATOR
- one restart would make the cheap path work: after a backend restart `--broker snapshot`
  answers B1 with no connection. NOT restarted here.
- re-run before relying on it: `python -m global_index.b1_audit --broker ibkr --record`
  (read-only; run when no window is open; the record expires after 24h on purpose)

---

## Task: 5ZP follow-up - the three panel inconsistencies 5ZP did not measure
Status: DONE (2026-08-26 ET 05:50-06:40). NOTHING RESTARTED. NO runtime file changed.
Two stylesheets only. No JS, no Python, no gate. orders_possible still false, 3 blockers.

### Why there was a follow-up at all
5ZP proved STRUCTURE (sections inside the panel; label above value) and never measured
how the content inside was PAINTED. Operator looked at the screen and asked. Measured in
chromium, three things were wrong, and one 5ZP claim was wrong as written:
**"the panel now uses the same shape as `.schedule-fact` next door"** - it used the same
CARD and none of the cell (padding 0 vs 16px 20px).

### 1. Every panel line was wearing journal-ROW chrome
`.journal li` (realtime.css:393) dresses a top-level journal row - 3px rail, hairline
under it, bullet dot, `margin: 0 -10px` bleed - and it matches **by descent**, so every
`li` inside an expanded panel got it. A seven-line Operational block drew **7 rails, 7
hairlines, 7 dots**, and each line sat **10px outside** the band's own text column
(measured: label x=1526, line x=1516). Also the only body text in the card set in
`--muted`/500 - dimmer AND heavier than the paragraphs beside it.
Fix: `.job-detail li { margin: 0; border: 0 }` + `::before { content: none }` (reset at
the PANEL, so the next list added does not have to remember), and the skin's body-text
rule now names the `li` so one declaration owns the panel's ink.
**Measured after**: line box, font and colour are IDENTICAL to `.job-resolution p`.

### 2. Track 1 panel borrowed the card, not the cell
`#track1Facts` carries `.now-schedule-facts` (the card) but its children are `.fact`,
while every skin rule is written for `> .schedule-fact`. Result: padding **0px**, no
dividers, label in **mono 700** where the whole page uses sans 500.
Fix: the inset is now `--fact-pad`, declared once on the container (base 9px 11px, skin
16px 20px) and READ by both grids, so they cannot drift; dividers drawn by each cell
casting a hairline on its own right and bottom edge, correct at 1, 2 or 4 columns
**without counting cells**; labels moved to the page's one label language.

### 2b. A defect I introduced and the screenshot caught
First attempt drew the dividers as `gap: 1px` over a hairline ground. 12 facts / 4 columns
leaves a **part-empty last row**, and a gap paints the space between cells AND the space
where there are none - so the empty remainder became a visible lighter block three cells
wide. Found by LOOKING at the render, not by any test. Now `box-shadow` on each cell, and
**test_9b** pins it: the fixture must have a part-empty last row (asserted, not assumed)
and the empty region must be indistinguishable from a cell.

### 3. The note under the panel was being cut off
`#track1Note` wears `.source-note` - built for the right-aligned one-liner beside a
heading: `max-width: 52%`, nowrap, ellipsis. Measured at 1920px: **1255px of text in a
736px box**, roughly two fifths never on screen, and the ragged left indent was the
right-alignment. Now a paragraph: left, wraps, no cap.

### Tests: 24 new (real chromium), ALL DERIVED not pinned
Lines compared to the paragraph beside them; Track 1 cell compared to the schedule cell
beside it. No literal padding or colour asserted, so a future change moves both or fails.
**Mutation sweep: 9/9 anchors go RED** (row-chrome reset, dot reset, footnote ink, cell
inset, dividers, the gap-ground defect, label language, note style, skin reading the shared
var). Baseline proven green first; digests compared as TEXT not bytes; both sheets restored
and verified. test_17 pins the reset is SCOPED - journal rows must KEEP their rail.

### The mutation harness itself reported a fake RED, once
One entry used `-k "test_9_and_not_9b"`, which is one identifier, not an expression. It
matched NOTHING, pytest exited 5, and an exit-code check read "nothing ran" as "went red".
Harness now checks tests were actually COLLECTED before believing any verdict.

### Regression: 596 passed, 0 failed (572 before + 24)
### Liveness: CSS only -> live at the next page load. Nothing to restart.
### Files touched
global_index/dash/realtime/realtime.css, global_index/dash/realtime-next/skin-e.css,
scratch/test_track1_dashboard_panel_consistency_20260826.py (new), TASK.md

---

## Task: Stage 5ZP - diagnostics polish: sleeve rule exposure + dashboard consistency
Status: DONE (2026-08-26 ET 04:30-05:40). NOTHING RESTARTED. NO runtime file changed.
No strategy decision/threshold/cap/identity touched. **Nothing recomputed in diagnostics.**

### The ten answers
1. runtime file changed? **NO**   2. orders impossible? **YES** (3 blockers)
3. chip: **three separate faults** fixed (below)
4. details inside the detail block? **YES** - asserted structurally, not by looking
5. Track 1 panel consistent? **PARTLY - this answer was wrong as written.** The label/value
   stacking was fixed; the CELL kept padding 0 and no dividers, because `.fact` is not
   `.schedule-fact`. Corrected in the 5ZP follow-up block above.
6. new rule values exposed? **NO, deliberately** - there are none to expose (below)
7. anything recomputed? **NO**
8. mobile/overflow? **PASSED** at 380 / 720 / 1024 px, expanded
9. data proof? **YES**, all three states, one line inside Operational
10. remaining: 5, unchanged

### THE CHIP - three faults, not one
- the TEXT doubled itself ("Signal NO SIGNAL") - "Signal" was already implied by its position
- it was a BORDERED PILL of its own invention while every other chip is `.event-status`
- **`grid-column: 1 / -1`** is literally what put it on its own line - the whole of the
  "own row, too large" complaint was ONE property
Now: `.event-status signal-<tone>`, label only, emitted INSIDE `.job-badges`.
**Measured**: a Track 1 row and a row with no chip are the same height within 2px.

### THE DETAIL BLOCK
Was `renderJobDetails(...) + operationalDetails(job) + signalDetails(job)` - SIBLINGS of the
panel, which is exactly why they rendered as loose text. Now inside `<div class="job-detail">`
after EVIDENCE/RESOLUTION. **Asserted by counting `.job-section` nodes OUTSIDE `.job-detail`
and requiring zero** - a question a text search cannot answer.

### A SENTENCE THAT NAMED A CAUSE WHICH DID NOT ACT
**Measured on the live journal**: 22 NO_SIGNAL rows on 2026-08-26, `candidates: []`,
`freshness_allow: false` - every one printed *"First rule that failed: Freshness check."*
Freshness stopped NOTHING; nothing reached admission for it to stop.
Now: *"Freshness check: measured as not allowing admission, but no candidate reached admission."*
**Kept narrow**: a rule that DID block a candidate is still named; a SETUP rule that failed with
no candidate is still named (there it IS why no candidate exists). Pinned against the real
journal, not just a fixture.

### NO NEW RULE VALUES EXPOSED - and that is the finding
210 of 324 checks still return `not_exposed_by_sleeve`. The detectors do not return their
measured values, and the ONLY way to put a number on the panel would be to COMPUTE it there -
a second implementation beside the one that trades, which would disagree on exactly the day it
mattered and the screen copy would be the one that looked right.
**Making the detectors return their values is STRATEGY-LAYER work, not a dashboard change.**
Recorded, not half-done.

### THE SUMMARY PANEL
`#track1Facts` only ever set `min-width: 0`, so label and value ran together. Now a small
uppercase label above, value beneath, wrapping allowed.
**CORRECTION (5ZP follow-up)**: "the same shape as `.schedule-fact`" was written here and
was NOT true - only the STACKING changed. The cell kept `padding: 0` and no dividers,
because the skin dresses `.schedule-fact` and these cells are `.fact`. Fixed in the
follow-up block at the top of this file.
Blocking gates render as **wrapping chips in plain English** with the raw id in the tooltip
("Account / legacy retirement gate", tooltip `B1_broker_account_or_legacy_retirement`).
**Measured**: with three gates the panel's scrollWidth does not exceed its clientWidth.

### Tests: 31 (real chromium). Regression **572 passed, 0 failed**
All browser suites included: realtime_dom, realtime_skin, realtime_contract, dashboard_backend,
paper_dom. Structural assertions throughout (child-of, computed grid-column, nodes outside the
panel, overhang, document scrollWidth). **4 tests are NOT browser tests** - the DOM test for the
freshness wording renders a FIXTURE and would stay green if the backend regressed, so the
composer is asked directly, including once against the real journal.

### 16 pins in 5ZD/5ZE updated (they pinned the OLD chip)
- **one got STRONGER**: 5ZE test_41 now checks the chip IS the shared component, not that a
  bespoke pill borrowed three properties from it
- **one INVERTED**: 5ZD test_46 asserted `grid-column: 1 / -1` - the defect - now requires its absence
- **one failed for a reason worth recording**: 5ZD test_47 searches the renderer for chip labels
  and went red because **my new COMMENT quoted the old label to explain why it was gone** -
  substring-over-prose, on a test built to catch a different trap. It now strips line comments
  and reads what the renderer EMITS.

### Liveness
JS/CSS are static assets served fresh on reload -> **every visual change is live now**.
The corrected sentence lives in `track1_signals`, imported at module load -> **the running
backend still composes the old sentence until restarted**.

### REMAINING BEFORE PAPER (5, unchanged - this stage touched no gate)
machine sleep (operator) | B1 (operator) | five clean days (time) | regime gate first PASS
(time, `--verify-strict` live) | broker stop proof + partials + in-flight restart (paper only)
**Two smaller items now RECORDED rather than open**: detectors do not return measured values;
nothing records whether the provider's last bar was open (5ZO). Neither blocks anything.

### Files touched
NEW: scratch/test_track1_stage5zp_dashboard_polish_20260826.py
MOD: global_index/dash/realtime/realtime.js, realtime.css, global_index/track1_signals.py,
     scratch/test_track1_stage5zd_..., scratch/test_track1_stage5ze_...,
     docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

---

## PENDING (Option C — user must run)
- [x] **VERIFY PASS**: python -X utf8 global_index/verify_concat_desired.py --data-dir data\cache\futures\frozen_sim --regime-csv spy_daily_live.csv --n 30
      30/30 Scenario A + B both PASS. "concat(parquet+live) → desired_position() == backtest" CONFIRMED.
- [x] CRON: continuous runner 14:10–15:55 ET (every 5 min) — IMPLEMENTED in run_scheduler.py 2026-07-22
      Root cause: backtest_swing_tf needs ≥2 bars in TF window; at 14:05 only 1 bar exists →
      0 loop iterations → 0% same-day TF entry capture at initial slot alone.
      Without fix: TF entries only via rollover path (D+1 14:05), overnight gap median $14 std $276
      vs 2-tick backtest assumption → slippage 10–30× larger than model.
      Fix: _live_day_body() extracted as shared body; _CONT_SLOTS loop adds 22 jobs (14:10→15:55).
      Pre-flight gate applied to all slots — if 13:45 update fails, entire window skipped.
      Capture rate: 14:10→22%, 14:30→50%, 15:55→100% (measured: check_resumebar_timing.py).
      Ref: check_resumebar_timing.py, check_rollover_gap.py (analysis scripts).
- [x] LIVE verify (P0c) ✅ DONE 2026-07-28/30 — xem SESSION bên dưới
- [~] ~~STRESS_MID Phase C2: add 10:20 ET morning cron~~ → **KHÔNG NỐI** (quyết định
      2026-08-08). Đây KHÔNG phải việc kỹ thuật còn dang dở — xem sub-task
      "STRESS_MID — quyết định KHÔNG NỐI" bên dưới trước khi làm bất cứ gì với nó.

### Completed (Offline bug fixes — 2026-07-08)
- [x] Fill.status + filled_qty + avg_price + error_msg (broker.py) — backwards-compat defaults; MockBroker → status="FILLED"
- [x] OpenPos.exit_pending: bool = False (live_decision.py) — persist + restore; _openpos_to_dict/from_dict
- [x] I4.8: capture fill return in CLOSE loop (runner.py) — if FAILED: exit_pending=True + restore to open_positions
- [x] _retry_pending_exits() skeleton (runner.py) — retries exit_pending positions at start of next run_day
- [x] STRESS_MID 2-pass (runner.py) — same-day entries (pass 1) → H4 sync → multi-day entries (pass 2); HALT_DAY now covers STRESS_MID same-session loss
- [x] T7.4 updated (expected_keys includes exit_pending); T30 exit_pending persist/restore; T31 STRESS 2-pass HALT_DAY
- [x] docs/futures/IBKR_TODO.md: B3/A1-A5/P2/P3/Roll items (blocked on IBKR account)
- **123/123 ALL PASS** (was 116/116); baseline $52,961.74 diff=$0.00 intact

### Completed (Sweep 3 — protected-file fixes — 2026-07-08)
- [x] signal_layer.py Zone 4: _asof_naive NaN bypass bug fixed — raises ValueError on empty/all-NaN ATR series; to_candidate raises on NaN risk_sized; C4 cluster try/except catches both
- [x] _validated_core.py Change 1 (safe): silent HMM exception — added logger.error + `import logging` + `logger = getLogger(__name__)`; no control flow change
- [x] _validated_core.py Change 2 (guard): ATR=0 → `da > 0` added to chandelier guard (`if not np.isnan(da) and da > 0 and len(high):`)
- [x] VERIFY PASS — 4 reconciles + baseline: gd0/stress/nkd/swing_desired all 0 mismatch; deploy_sim 2-tick = $52,936 / Calmar 2.74 UNCHANGED

### Completed (Scaling docs correction — 2026-07-08)
- [x] Measured n=2 @$55,784: MaxDD=$3,810 (không phải $5,890 — NKD bug trong scaling_dd_trust.py inflate)
- [x] Confirmed threshold self-referential: $55,784 dùng MaxDD@$50k, tại $55,784 dd_scale=1.92<2 → sizer vẫn n=1
- [x] Three-way inconsistency documented: $55,784 doc / ~$58-59k true threshold / Calmar 2.28 < floor 2.38
- [x] SCALING_ANALYSIS.md: full analysis, data table, root cause structural, 4 alternatives, threshold recompute
- [x] Corrected in-place tất cả docs (DECISIONS, ASSUMPTIONS, ISSUES_LOG, OPEN_QUESTIONS, STATUS, LESSONS, GLOSSARY, ARCHIVE_LOG, SCRIPT_INVENTORY, README)
- n=1 ceiling decision added to DECISIONS.md; 3 open questions added to OPEN_QUESTIONS.md

### Completed (Divergence Sweep — 2026-07-04)
- [x] UT-2 FIXED: generate_today_signals stale-price retry guard (swing + NKD); same-direction rollover via force_entries
- [x] UT-5 FIXED: NKD date alignment — replaced nkd_today_norm with today_norm (ET); late-feed suppressed (conservative)
- [x] UT-1 closed: FuturesRunner requires breaker as positional arg; verified TypeError on omission; both callers updated
- [x] UT-3 closed: same-day state-diff path structurally dead in live (no exit field); synthetic injection PASS
- [x] UT-4 closed: half-day CME — A1-A4 PASS (no crash, no entry, position carries through)
- [x] WARN documented: size_multiplier=0.5 intentionally not wired; binary protection design confirmed
- [x] NKD operational constraint documented in runner.py + DIVERGENCE_SWEEP.md: runner must execute after ~02:30 ET
- [x] E-injection C1-C7 tested:
      C1 (late bar) PASS, C2 (dup bar) PASS, C3 (out-of-order) no crash/documented,
      C4 (missing bars) PASS, C7 (NKD late) PASS (UT-5 covers)
      C5 (reconnect double-count) FAIL — pre-live: IBKRBroker must reconcile state on reconnect
      C6 (uppercase OHLC) FAIL — pre-live: IBKRBroker must lowercase column names on ingestion
- [x] Final verify_runner_real: $52,961.74 diff=$0.00 ALL PASS — baseline preserved through all sweep work
- [x] UT-6 and UT-1: remain 🟡 Medium (path dead by design, no code change needed)

### Completed (IBKRBroker C3/C5/C6 — 2026-07-04)
- [x] global_index/ibkr_broker.py: IBKRBroker implementing Broker ABC with 3 mandatory specs:
      C3: fetch_bars sort_index() — unsorted IBKR bars corrupt chandelier ratchet
      C5: reconcile_positions(runner_state) — dedup (inst, cluster) after reconnect double-count
      C6: fetch_bars lowercase columns — IBKR uppercase OHLCV crashes engine
      _raw_fetcher injection point for offline testing (no live Gateway needed)
- [x] global_index/test_ibkr_injection.py: 14/14 PASS (C3: 3/3, C6: 4/4, C5: 7/7)
      C5.7 contrast proves: WITHOUT reconcile pnl doubled ($50,300 vs expected $50,150)

### Completed (HMM stale guards G1/G2/G3 — 2026-07-05)
- [x] global_index/notify.py: mirror của raits/live/notify.py (boxed stderr + push hook)
- [x] global_index/hmm_stale_guard.py: HMMStaleGuard — G1 + G2
      G1: SOFT >2bday → notify WARN once; HARD >5bday → regime_unreliable=True + HALTED
      G1: Recovery ≤2bday → RESUMED + clear flag (chống oscillation: recovery==soft < hard)
      G2: SOFT >12mo → MODEL AGE WARN once; HARD >18mo → MODEL AGE URGENT once (no halt)
      entries_blocked counter; check_day(today, spy_last_date_override) for offline testing
- [x] futures/refreeze.py: G3 _check_spy_coverage() — ABORT + notify + ValueError if CSV < fit_end
- [x] global_index/runner.py: FuturesRunner(hmm_stale_guard=None) — optional guard
      run_day(_spy_last_date_override=None) — passes override to guard.check_day()
      entries cleared when regime_unreliable; exits run normally via state.open_positions
- [x] global_index/test_hmm_stale.py: 42/42 ALL PASS
      G1.12-G1.16: exit runs (equity +$300), entries blocked, counter=1, HALTED notified
      G2: warn-only confirmed (regime_unreliable never True from G2)
      G3: ValueError + REFREEZE ABORTED + CSV>=fit_end passes
      base: runner without guard — entries admitted normally (backward compatible)
      noharm: HMMEngine git log clean

### Completed (HMM Re-freeze mechanism GĐ3 Phần A — 2026-07-05)
- [x] futures/refreeze.py: full anchored-expanding re-freeze pipeline
      refreeze_hmm(anchor, fit_end, spy_csv) — calls label_regimes() unchanged, never modifies HMMEngine
      run_gate() — 3-branch: AUTO_APPROVE (<5%), VERIFY (5-15% or any calm-flip), HOLD (≥15% or calm-flip>10)
      run_verify() — injectable mock verify_fn; auto-rollback on fail
      apply_freeze() + rollback() + current_freeze() — JSON registry with history[:3]
      run_refreeze_pipeline() — full orchestration with graceful G3 failure handling:
        - ValueError (CSV<fit_end) → fail_type=data_missing, pending flag, no crash
        - Unexpected error → fail_type=unexpected, pending flag, log.exception
        - Every subsequent run re-alerts if pending flag present (_alert_if_pending)
        - Success: pending flag cleared, model promoted normally
      Registry: models/hmm/futures_freeze_registry.json
      Pending flag: models/hmm/refreeze_pending.json
- [x] futures/test_refreeze.py: 60/60 PASS (T1-T11)
      T1-T7: cold-start, gate branches, full-chain, rollback, 3-gate boundary, calm-flip rule, no-harm
      T8: short CSV → graceful fail, failed=True, fail_type=data_missing, REFREEZE FAILED notified
      T9: pending flag written with attempts=1, fail_type, fit_end_target
      T10: repeat fail → STILL PENDING re-alerts, attempts=2
      T11: success with real CSV + seeded pending (attempts=3) → flag cleared, swapped=True, STILL PENDING fired once

### Completed (Futures Trust Audit — 2026-07-05)
- [x] STEP 1: Liệt kê số load-bearing + traceability classification
      TRACEABLE (script committed): $52,962/Calmar 2.75 | degradation 2.38 | fit_C 17.16% | divergence counts | T2 1.13%
      ONLY-FROM-REPORT: STRESS_MID 2022 $5,296 | 2-micro DD $9,854/$82k threshold | 83/101 flip per-year
- [x] STEP 2A: stress_mid_trust.py committed — re-measures STRESS_MID per-year P&L (fit_C, 2t slip)
      Standalone 2022: measured +$6,632 vs claimed +$5,296 (delta +$1,336) → CONFIRMED
      Swing 2022: measured -$555 vs claimed -$232 (fit_C more Stress days → more STRESS_MID activity)
      Marginal with cap 2022: +$2,208 (NKD also helps 2022, some cap displacement)
      VERDICT: STRESS hedge role CONFIRMED, fit_C even stronger
- [x] STEP 2B: scaling_dd_trust.py committed — re-measures 2-micro MaxDD + sizer threshold
      1-micro MaxDD: $2,789 — MATCH baseline ✓
      2-micro MaxDD (force n=2, with cap): $5,890 vs claimed $9,854 — DIFFERS ($3,964 gap)
      Sizer n=2 threshold (formula): $55,784 vs claimed $82k — GAP ($26k = 47% manual buffer)
      ROOT CAUSE: $9,854 = old pre-NKD MaxDD $5,185 × ~1.9 (stale estimate). $82k has no formula derivation.
      NEW GATE: sizer formula gives n=2 at ~$55,784 (DD-binding). $82k is conservative but unverified.
- [x] STEP 2C: hmm_flip_year_trust.py committed — per-year flip breakdown fit_A vs fit_C
      17.16% A→C pct change: CONFIRMED ✓ | 101 Normal→Stress: CONFIRMED ✓ | 83 in 2020+2022: CONFIRMED ✓
- [x] STEP 3 interpret: STRESS role solid; scaling gate should use $55,784 (formula) not $82k (unverified)
- [x] STEP 4 defer: divergence coverage counts (reconcile scripts traceable, sweep closed) → TODO not urgent

### Completed (Pre-paper milestone + docs — 2026-07-08)
- [x] STATUS.md rewrite — PRE-PAPER MILESTONE (NỀN/VAULT/AN TOÀN/BUG SWEEP/SCALING/BLOCKER/GIỚI HẠN)
- [x] ISSUES_LOG.md: I4.8 update (OFFLINE DONE), I4.9/I4.10/I4.11 added, NHÓM 4B sweep findings (F1/F2/F3)
- [x] LESSONS.md: L10 added (reconcile = consistency not correctness)
- [x] OPEN_QUESTIONS.md: Bug Sweep section (offline cạn, F1/F2 monitor)
- [x] IBKR_TODO.md: account APPROVED, thứ tự implement wired

### Completed (GIAI ĐOẠN 1 — _fetch_raw() + connect test — 2026-07-08) ✓ LIVE VERIFIED
- [x] P2 timezone: ib_insync 0.9.86 trả `datetime64[us, US/Central]` (tz-aware Chicago).
      Fix: `tz_convert("America/New_York").tz_localize(None)` → ET naive đúng.
      VERIFIED: first_bar=2026-07-06 18:00:00 ET (CME Globex open chính xác), 1380 bars/day (23h session)
- [x] Contract ambiguity: `ibi.Future("MES", exchange="CME")` bị reject (nhiều contract month).
      Fix: `_current_front_month(inst)` → lookup ROLL_SCHEDULE → dùng `lastTradeDateOrContractMonth="202609"`
- [x] get_equity() hang: `reqAccountUpdates()` gây block — ib_insync đã auto-subscribe on connect.
      Fix: remove `reqAccountUpdates()`, dùng `ib.sleep(2.0)` + `ib.accountValues()`
- [x] IB Gateway paper port = **4002** (không phải 7497 — đó là TWS paper port)
- [x] `connect_test_paper.py` **9/9 PASS** (live, paper account DUR125337, equity CA$1,000,480):
      CON.1 connect | CON.2 equity | DATA.1 2701 bars | DATA.2 lowercase | DATA.3 sorted | DATA.4 datetime64
      P2.1 session open 18:00 ET | P2.2 1380 bars/day | P2.3 tz-naive
- [x] VERIFY: 247/247 offline tests ALL PASS; baseline unchanged

### Completed (Wire session 2026-07-08/09 — print-signals LIVE VERIFIED)
- [x] Cold start safety verified from code: `new_ed == day_ts` guard + diff_desired_vs_held(held=[]) = 0 entries, 0 exits
      All branches (swing/NKD/force_entries/STRESS/exits) safe when held=[]. No spurious CLOSE possible.
- [x] spy_daily_vault2025.csv verified safe (MEASURED):
      label_regimes: 1761/1761 dates 2018-2024 IDENTICAL between frozen vs vault2025 CSV
      Features (log_return + 5-day rolling vol) are purely local — adding 2025-2026 data cannot change old labels
      baseline $52,936 / Calmar 2.744 unchanged; vault2025.csv safe for live --regime-csv
- [x] IBKR 162 "Historical data query cancelled" root cause: stale Gateway session state
      Fix: restart IB Gateway + `timeout=120` in reqHistoricalData + `time.sleep(15)` post-connect
      Files: global_index/ibkr_broker.py (timeout=120), global_index/run_live_day.py (15s sleep)
- [x] --print-signals LIVE VERIFIED 2026-07-09 with vault2025.csv:
      regime=Normal (decoded thật, không carry-forward từ vault2025.csv)
      bars=MES✓1741b MNQ✓1741b MYM✓1741b M2K✓1741b MNKD✓1734b
      entries=0 exits=0 (expected: cold start + no backtest entry on today's date)
      swing=3055 nkd=879 stress=474 (parquet covers 2026-07-07 → backtest has 2025-2026 trades)

### Completed (Live Runner Audit — 2026-07-09)
- [x] Full audit: live runner vs strategy design — 6 mismatches found (A–F)
      Root cause: `run_live_day.py` copied timeline lookup from `verify_runner_real.py` (O(n) 8yr replay)
      instead of calling `generate_today_signals()`. runner.py docstring says intent correctly, implementation violates it.
      Impact measured: fire median 14:45 ET, 40% after 15:00; live@15:55 delta = −$9,112 (−20.2% of BT P&L)
      UT-2/UT-5 fixes in `signal_layer.py` are dead code (generate_today_signals not called in prod)
      Fix plan written: docs/futures/LIVE_RUNNER_AUDIT.md
      Fix = Option C: runner.py 1-line (through=end-of-day) + run_live_day.py signal_fn replacement + 5-min cron

### Completed (BUILD STP — overnight stop order — 2026-07-10)
- [x] **Exit timing gap measured**: 96.4% of chandelier/GAP exits fall outside 14:05–15:55 cron window.
      Mean signed delta = -$19.09/trade (live@cron vs backtest@stop). Total drag = -$38,246 vs baseline $41,266.
      ROOT CAUSE: cron sends CLOSE at market price (~14:05 open) vs backtest exits at exact stop level.
      Decision: BUILD STP (not accept for paper). See scratchpad/measure_overnight_stop_miss.py.
- [x] **live_decision.py**: `OpenPos` + `stop_price: float | None` + `stop_order_id: str | None`
- [x] **broker.py**: `Broker` ABC + `MockBroker` — `place_stop()`, `cancel_order()`, `get_order_status()`
- [x] **ibkr_broker.py**: `IBKRBroker.place_stop()` (GTC STP, outsideRth=True), `cancel_order()`, `get_order_status()`
- [x] **runner.py**:
      `_openpos_to_dict/from_dict`: serialise `stop_price` + `stop_order_id` (backward-compat `.get()`)
      Pass 2 multi-day OPEN: capture fill → place GTC STP immediately after FILLED/PARTIAL; ALERT on failure
      B3 STP-aware: if file pos has stop_order_id → `get_order_status()` → FILLED = auto-clear (no halt);
      NOT_FOUND = CRITICAL with STP hint ("check TWS executions")
- [x] **test_stp.py**: 8/8 PASS — STP1 (place called), STP2 (JSON roundtrip + legacy None), STP3 (no STP sameday),
      STP4 (no STP on CANCELLED OPEN), STP5 (B3 STP EXIT auto-clear), STP6 (NOT_FOUND halts), STP7 (no-STP original behavior)
- [x] **Full suite**: 14/14 ibkr_injection + 50/50 pytest (operational_fixes + event_playback + stp) ALL PASS
- **Note**: stop_price = ENTRY chandelier level only. Ratchet updates (trailing stop as chandelier moves)
  planned for a future phase; paper phase uses fixed entry-stop. Covers 95%+ of the -$38k drag.

### Completed (Causal fix + pre-paper verification — 2026-07-10)
- [x] Look-ahead bug fixed in `futures/_validated_core.py::backtest_swing_tf`:
      `exit_ts_today` reset per day, set on exit, `win = win[win.index > exit_ts_today]` blocks retroactive entries.
      VERIFIED: deploy_sim baseline Calmar=1.72 ($41,266), floor=1.53 (was dirty 2.38/2.04/3.08/3.35).
- [x] INVARIANTS.md updated: all 4 causal numbers; old dirty numbers deprecated with note.
- [x] 2.04 hardcoded → 1.53 in: generate_replay_snapshots.py (_BACKTEST_CALMAR), runner.py (backtest_calmar).
- [x] Reconcile all PASS after _validated_core change: GD0/STRESS/NKD Phase 1/SWING_DESIRED Phase 1 = 0 mismatch.
- [x] B-fail RESOLVED: 2 known cases GONE; 0 pairs with prior exit >15:55 in 1499 same-day pairs. VERDICT PASS.
- [x] 26/26 in-window pairs:
      CHECK A (causal invariant): PASS ✓ — all 26 entry_time > exit_time
      CHECK B: 26 pairs, lag 13–105 min (mean 41.7 min)
      CHECK C (desired_position at cron+5min): PASS ✓ — 26/26 MATCH (miss=0, mismatch=0)
      → OPTION C TIMING VERIFIED HOÀN TOÀN
- [x] Offline checklist confirmed via code trace:
      Re-entry prevention: structural (held_by_key, signal_layer.py:165-177)
      Cold-start guard: signal_layer.py:175 `new_ed == today_norm` rejects stale entry_day
      NKD timing: MNKD session_tz=Asia/Tokyo; 14:05 ET runner sees today_norm=X = entry_day=X → match ✓
- [x] B3 design gap fixed: `_b3_halt_entries` flag in runner.py:
      Init line 192 (before B3 block), set True line 260 on mismatch, gate line 623 in run_day().
      Exits unaffected; pattern consistent with D5/E3/HMM stale guards.
      test_ibkr_injection.py: 14/14 PASS.
- [x] B3 lifecycle confirmed: `run_live_day.py` là script chạy-và-thoát (không phải daemon).
      Mỗi cron invocation = new process → `__init__()` → halt=False → B3 re-check → auto-releases if fixed.
      KHÔNG cần reset thủ công; halt tự nhả ở cron N+1 sau khi operator sửa live_positions.json.
- [x] docs/futures/OPERATIONS.md: runbook mới — B3 (4 bước), D5 STOP_FILE, E1 PID lock, circuit breaker, log monitoring table.

### Completed (Live-path bug fixes — sessions 2026-07-11/12)
- [x] `_persist_state` typo fixed (run_maxhold_exit called `_persist_positions` → AttributeError on first MAX_HOLD exit). Commit: 4cec39e
- [x] Fix 1: `get_order_status` + `ib.openTrades()` — GTC STP survive TWS 17:00 restart. Commit: 42e1fc6
- [x] Fix 3: `get_equity` retry 4×(2–5s) = ~14s — equity=0 on connect = subscription settling, not error. Commit: 42e1fc6
- [x] Fix 4: `place_stop` orderId retry 10×0.3s — ib_insync async assign. Commit: 42e1fc6
- [x] Fix 2 (STP-VERIFY): `runner.py` B3 STP-INFER → VERIFY. NOT_FOUND+qty==0 → `find_execution()` (reqExecutions server-side, 2-day lookback); True=clean state, False=HALT. Commit: 9db2f93
- [x] `get_positions()` retry-until-stable (4 reads × 2s, max 8s) — sleep cố định không verify settle. Commit: 9db2f93
- [x] B3 EMPTY-WARN: file-có-position + IBKR-empty → WARNING banner; mismatch loop HALT trừ STP-VERIFY confirmed. Commit: 9db2f93
- [x] C1 fill quality logging + running mean: signed slippage OPEN + CLOSE (LONG/SHORT direction-aware). runner.py:865-883, 989-1005. ADVERSE/favorable labeled, %+.4f preserves sign. Running mean persisted cross-session in slip_stats.json (atomic write via .tmp→os.replace).
- [x] _strip_tz fix: `_concat_live` + `_concat_nkd_live` — frozen parquet (tz-aware US/Eastern from load_parquet) concat with live bars (tz-naive ET from fetch_bars) caused TypeError in sort_index(). Fix: _strip_tz() helper strips tz before concat; MAX_HOLD searchsorted in _validated_core.py:257-266 verified safe for naive ET.
- [x] **B1 PASS**: `verify_concat_desired.py` 30/30 PASS — Scenario A (full-day concat) + Scenario B (partial-to-fire). "Live == backtest by construction" VERIFIED. Runtime ~10-15 min (label_regimes expanding-window HMM + _swing_cache 8y 1-min data × 4 instruments — not a hang, normal runtime).
- [x] **B2 PASS**: run_scheduler.py ET-native confirmed. Missing required args bug fixed (make_scheduler now accepts data_dir/nkd_parquet/regime_csv with defaults, wired via CLI). APScheduler 4.x next_run_time AttributeError fixed (getattr fallback).
- [x] **P0a PASS**: Plumbing verified on Gateway 4002 — equity/TZ/positions/fetch/HMM all OK.

### Key decision — B4 NKD (paper scope)
**Option B: swing-only first, NKD sau cert.**
- Paper phase bắt đầu với **MES/MNQ/MYM/M2K** (swing + stress). NKD thêm sau khi CME bundle + Rule 576 cert xong.
- **Hệ quả benchmark**: paper swing-only ≠ full backtest ($53,021 baseline). NKD chiếm ~645/(645+2706-645)≈25% tổng positions trong IS. So sánh paper P&L vs **swing-only IS subset** (chạy deploy_sim --exclude-nkd hoặc extract từ trade log là MES/MNQ/MYM/M2K + STRESS_MID).
- Paper metrics cần so vs swing-only baseline (không so 53k full system).
- Sau cert: add NKD, benchmark lại vs full $53,021.

### SESSION WRAP-UP (2026-07-11/12) — Chờ P0b thứ Hai
Status: OFFLINE DONE — chỉ chờ market day

#### Đã xong session này
- [x] C1 fill monitoring: signed slippage OPEN+CLOSE (adverse/favorable) + running mean persist cross-session (slip_stats.json). Committed.
- [x] _strip_tz: fix TZ mismatch concat frozen(tz-aware US/Eastern) vs live(tz-naive ET) → TypeError. MAX_HOLD searchsorted có nhánh naive, oracle 26/26 sau fix. Committed.
- [x] B1 verify_concat: 30/30 (3 runs độc lập) SAU _strip_tz fix — valid trên code hiện tại.
- [x] B2 cron: dry-run verify 14:05/09:31 ET — 3 cột ET/UTC/MDT cùng thời điểm, DST đúng, mon-fri. APScheduler 3.11.3.
- [x] P0a plumbing PASS: connect/equity>0/positions retry-stable/fetch 2760+2740 bar/HMM decode thật.
- [x] B5 account clean: broker empty + file positions:[] + production đọc đúng key + P0a không WARN — 4 nguồn đồng ý. Script verify bug (open_positions→bool(dict)) fixed, production đúng.
- [x] B2 TZ verify: CronTrigger.get_next_fire_time() — live_day=14:05 EDT/18:05 UTC/12:05 MDT, maxhold=09:31 EDT — cả 2 OK.

#### Trạng thái offline
ĐÓNG. Không còn bug đào offline. Bug tiếp lộ TRONG P0b/P2 khi chạy thật.

#### Đường đi đầy đủ → [docs/futures/PAPER_ROUTE.md](docs/futures/PAPER_ROUTE.md)

#### SESSION 2026-07-13 — Commits + Trạng thái

**5 commits session này:**
- `ba83e74` — splice anchor fix + MYM exchange CBOT + dtype guard + LESSONS/ISSUES_LOG/PAPER_ROUTE docs
- `0f91fc9` — pre-flight scheduler (update_ibkr_daily → update_spy_csv → fail-safe flag)
- `030de83` — Branch 3 parquet freshness fallback (ngay sau xóa)
- `90a7000` — xóa Branch 3 (loophole parquet-only bỏ spy_csv) → fail-closed 2-branch
- `8351fd6` — update_ibkr_daily `sys.exit(1)` khi instruments fail fetch

**Uncommitted (không cần commit):**
- `TASK.md` — living doc (cập nhật liên tục, không commit từng lần)
- `global_index/dashboard.html` — UI update, không ảnh hưởng logic
- `data/`, `global_index/data/` — parquet data (gitignored)
- `monitor/` — monitoring scripts, scope riêng

#### P0b — 2026-07-13 (thứ Hai — Calm, no entry)

**⚠️ P0b-A DONE / P0b-B ⏳ — đừng coi hôm nay = P0b đầy đủ:**
- **P0b-A (gate + logic)** ✅ DONE: gate (Calm→no entry) + offline logic (desired_basket=backtest 53124) verified
- **P0b-B (live path 4-field)** ⏳ CHỜ: chưa có entry thật → chưa so `--print-signals` vs `desired_basket()`. P0c.

**Bugs fixed (update_ibkr_daily.py, commit ba83e74):**
- [x] MYM exchange CME→CBOT — root cause CBOT exchange, chỉ lộ khi fetch thật
- [x] Dtype guard false positive — `equals()` dtype-strict, cast float64 fix
- [x] Splice anchor: `new_bars.index > last_existing` thay vì `iloc[0]` (first-fetched = 18:00 Sunday)
- [x] update_ibkr_daily exit(1) khi failed — pre-flight phát hiện đúng (commit 8351fd6)

**VIỆC 1 — Parquet catch-up:** ✓ (initial run; splice bug found + fixed mid-session)
**VIỆC 2 — Gate verify:** ✓ regime=Calm, 0 entries, 0 exits (live Gateway)
**VIỆC 3 — Logic verify (offline):** ✓ MYM entry=53124 MATCH post-fix, gap=0.00, frozen 23/23

**Splice offsets (sau repair):** MES=+11.5 / MNQ=+183.0 / MYM=−57.0 / M2K=+7.2 / MNKD=+1065.0  
**Sidecar `global_index/data/_splice_cuts_confirmed.json`:** GIỮ (audit trail splice boundary, không xóa)

**⚠️ MYM đặc biệt (P0c):** vừa fix exchange CBOT + splice offset (−57 vs +751). Kiểm scale MYM cẩn thận khi có entry.

#### SESSION 2026-07-13/14 — Monitor/Dashboard (commits f753b43, 50bd59e, 68ab035, f139fa5, 7e8a690)

**Backend + ibkr_reader.py:**
- [x] TEST 3 (clientId simultaneous 99+1): PASS — bars 1741 each (HMDS race condition explained)
- [x] TEST 4 (position + order parse): PASS — equity/positions/orders all fields correct
- [x] ibkr_reader.py Fix 1: equity=None on CAD account → collect all currencies, prefer BASE>USD>any
- [x] ibkr_reader.py Fix 2: orders=[] → `reqAllOpenOrders()` + sleep(1.0) before `openTrades()`
- [x] place_stop tif=GTC verified from code: ibkr_broker.py:749 explicit, not IBKR default

**Dashboard bước 2a (commit 50bd59e — verified running, không chỉ code):**
- [x] DL1–5: IBKR panel auto-refresh /api/all every 8s, SNAPSHOT divider, stale behavior
- [x] Stale on disconnect: giữ data + dim opacity 0.4 + "⚠ stale as of HH:MM"; clear chỉ khi backend offline
- [x] Verified browser: equity $994,294, MESU6 position, STP order, SNAPSHOT divider showing

**Dashboard bước 2b — runner.py observability (commits 68ab035 + f139fa5 + 7e8a690):**
- [x] regime_fn param → dump_state hiện regime thật (không "Unknown"); fallback "Unknown" nếu None
- [x] OPEN/CLOSE/STP events sau fill confirm; bound 500 đã có
- [x] scheduler: thêm `--live-state-path global_index/live_state_data.js` vào run_live_day call
- [x] Reconcile GĐ0+STRESS PASS sau cả 2 bước (diff $0.00)
- [x] End-to-end verify: --dry-run → live_state_data.js `"regime": "Calm"` → dashboard hiện Calm ✓

**Dashboard trạng thái cuối:**
- Loại 1 (account/equity/position/STP): ✅ real-time, 8s refresh, verified running
- Loại 2 regime: ✅ populate + end-to-end verified (Calm hiện đúng)
- Loại 2/3 signal/events: code done, reconcile PASS — fire ⏳ P2 (cần order thật)
- Control (start/stop): CHƯA — bước riêng sau P2

**LESSONS:**
- L11: "Code có" ≠ "chạy đúng" — DL2/3/4 đánh ✅ trước khi verify, phải chạy browser test
- L12: Sửa runner dù observability-only → PHẢI reconcile (gate cứng). Tách 2 commit để isolate failure.
- L13: scheduler cũng phải truyền đủ args cho subprocess — thiếu --live-state-path → dump_state no-op mãi

#### SESSION 2026-07-14 — Docs consolidation (DONE)

**A1-A6 verified từ code, 5 sửa PIPELINE_FLOW.md, cross-link 3 docs:**
- [x] A1 WRONG: `CONSTRUCTION (một lần khi khởi động)` → `label_regimes()` chạy TỪNG NGÀY (run-and-exit subprocess). Đã sửa dòng 17 + 236 PIPELINE_FLOW.md
- [x] A2: `positions.json` trong ASCII art (dòng 207) → `live_positions.json`. Dòng 240 tương tự.
- [x] A3: "5 instruments + NKD" → "4 instruments MES/MNQ/MYM/M2K + NKD = 5 total"
- [x] A4: deploy_sim docstring dùng `spy_daily.csv` (stale); RUNBOOK baseline verify dùng `spy_daily_live.csv`. Không có mâu thuẫn — deploy_sim nhận bất kỳ arg `--regime-csv`.
- [x] A5: $52,936 = original baseline bị mất (RUNBOOK intro). $40,919 = deploy_sim frozen_sim baseline hiện tại (RUNBOOK "Expected: net=$40,919"). Khác scope, không mâu thuẫn.
- [x] A6: G1 chưa wire — xác nhận lại (hmm_stale_guard=None, I5.12).
- [x] Cross-links thêm vào cả 3 docs (PIPELINE_FLOW ↔ DAILY_FLOW ↔ DAILY_UPDATE_RUNBOOK)
- [x] Date update: DAILY_UPDATE_RUNBOOK 2026-07-12 → 2026-07-14

**Single source of truth phân công:**
- DAILY_FLOW.md = "khi nào / cái gì chạy" (command timeline, phase P0c/P1/P2)
- PIPELINE_FLOW.md = "bên trong run_day() hoạt động thế nào" (step-by-step runner logic)
- DAILY_UPDATE_RUNBOOK.md = "data safety" (frozen/live ranh giới, backup, rollback, anti-patterns)

#### SESSION 2026-07-15 — Pyramiding research ĐÓNG (NO-GO) — quay lại P0c

**Câu hỏi:** pyramiding/scale-in trên SwingTF (max_units sweep {1,2,3,4}) có add edge không?
**Verdict: NO-GO** — max_units=1 (không pyramid) tối ưu. Đóng câu hỏi, KHÔNG build vào production.
- [x] Variant TÁCH: `futures/swing_tf_pyramid.py` + `pyramid_wfo.py` (không đụng production/vault/paper)
- [x] GATE pass: max_units=1 == `_validated_core.backtest_swing_tf` trade-for-trade EXACT (4 instr)
- [x] Sweep A (risk-constant): Calmar monotonic worse 1.13→0.60→0.23→0.20; expectancy $18→$3.5
- [x] Sweep B (risk-grows): Calmar IDENTICAL A ($ cao thuần leverage); MaxDD mu≥2 vượt 15% cap → loại deploy
- [x] Commits RIÊNG: `5910401` (A) / `40758e7` (B); doc LESSONS L16; memory `project_pyramiding_results`
- [x] Vault UNTOUCHED (IS-only, vault_start=2023-01-01 hardcode)
- Lý do: adds vào +kN muộn/cao → dilute; WR ~17% high-payoff → loãng payoff. Chi tiết: LESSONS.md L16.
- **⚠️ Scope:** NO-GO cho pyramid-kiểu-này + strategy này + window này; không general mọi nơi.

**→ Quay lại P0c** (chờ Normal/Stress verify cutoff I5.11 + live 4-field). Pyramid không đổi lộ trình paper.

#### SESSION 2026-07-16 — Execution prep (không cần Normal/Stress)

**Items đã xong (không đụng order, giữ scheduler dry-run):**
- [x] **G1 wired vào run_live_day.py** (I5.12 DONE):
      `HMMStaleGuard(regime_csv=a.regime_csv, fit_end=HMM_FIT_END)` → FuturesRunner ctor
      Dùng `a.regime_csv` (= `spy_daily_live.csv` từ scheduler) — KHÔNG frozen `spy_daily.csv`
      Help text + usage docstring cũng cập nhật; hmm_stale_guard.py wire example sửa spy_daily_live.csv
- [x] **test_hmm_stale.py**: 42/42 ALL PASS (G1/G2/G3 logic + runner integration + baseline + no-harm)
- [x] **False-positive check**: gap=0 bday → `entries_ok=True`, `regime_unreliable=False` → G1 không block oan ngày fresh
      G2 MODEL AGE URGENT expected (model 19 tháng = 2024-12-31 → 2026-07-16) — warn only, không halt
- [x] **test_stp.py**: 9/9 ALL PASS (STP1–STP8, MockBroker — live verify chờ P2 có position thật)
- [x] **Docstring fix _handle_rollover**: "NOT YET IMPLEMENTED" → "Code implemented. Not yet tested against live IBKR"
      Commit riêng (doc only, không đổi hành vi)
- [x] **MAX_HOLD exit logic**: verify qua MockBroker — hold≥5d CLOSED, hold<5d kept. Script thật cần Gateway nên test qua FuturesRunner trực tiếp.
- [x] **Scheduler giữ dry-run**: KHÔNG bật non-dry-run — chờ G1 wire verify + 4-field verify (P0c) xong

**⚠️ G2 MODEL AGE URGENT hiện tại:** 19 tháng (fit_end=2024-12-31). Warn-only, KHÔNG halt. Nhắc nhở re-freeze — lên kế hoạch sau paper.

#### P0c — ✅ DONE 2026-07-28/30

**Kết quả:**

| Instrument | Ngày | Direction | Entry | Stop | Kết quả |
|------------|------|-----------|-------|------|---------|
| MNKD (NKD) | 2026-07-28 | LONG | 62720.00 | 62601.43 | ✅ PASS |
| MYM (Swing) | 2026-07-30 | LONG | 52310.00 | 52234.25 | ✅ PASS |
| M2K (Swing) | 2026-07-30 | LONG | 2949.20 | 2944.78 | ✅ PASS |
| MES, MNQ | 2026-07-30 | (None) | — | — | ✅ Consistent (None cả hai path) |

**Phát hiện quan trọng trong P0c:**
1. **P0c cần IBKR live bars** — frozen parquet đến ~13:45 ET; NKD signal fire trong cửa sổ 13:45-15:35 ET (live từ IBKR). Verify offline-only → None hoặc wrong direction. Fix: thêm IBKR connect + `fetch_bars()` vào cả 2 verify scripts.
2. **desired_position() = full backtest replay** — thêm bars có thể đổi last open trade (trade cũ close → trade mới open). Lý do ban đầu MNKD ra SHORT 63630 từ parquet, nhưng live path thấy LONG 62720.
3. **NKD frozen parquet tz** — tz_convert(Asia/Tokyo) → _strip_tz → JST-naive. Live bars IBKR = ET-naive. concat hoạt động trong thực tế (không overlap).
4. **HMM non-determinism** — label_regimes() re-fit mỗi lần → borderline days có thể flip regime giữa các lần chạy. Pre-existing, deferred.

**Files được tạo:**
- `d:\raits\p0c_verify_mnkd.py` — verify NKD: IBKR connect + fetch MNKD + desired_position()
- `d:\raits\p0c_verify_swing.py` — verify Swing: IBKR connect + fetch 4 instr + desired_basket()
- `d:\raits\p0c_overnight.py` — tự động chạy --print-signals 14:05-15:55 ET + auto-run p0c_verify_swing.py khi detect ENTRY; startup_check(); Polygon key auto-load

**p0c_overnight.py auto-verify flow:**
```
job_print_signals() → _run_capture(--print-signals)
  → _has_swing_entry(output)? → YES
    → _run_capture(p0c_verify_swing.py --port 4002 --client-id 92)
    → save block to p0c_signals_MMDD.txt
```

**Bug fixes trong P0c sessions:**
- `p0c_verify_swing.py`: UnicodeEncodeError khi run làm subprocess từ p0c_overnight.py (stdout cp1252 + tiếng Việt "Rổ 4"). Fix: `sys.stdout.reconfigure(encoding="utf-8")` wrapped try/except.
- `p0c_overnight.py`: Polygon key từ `config_private.py` (Python variable, không phải OS env). Fix: module-level auto-load vào `os.environ["POLYGON_API_KEY"]`.
- startup_check(): 4 checks (Polygon key / NKD parquet + spy_csv + p0c_verify_swing.py / swing parquets / IBKR reachable via client_id=99).

**⚠️ IBKR slot overlap** (chưa fix): P0C_1440/1450 fail do --print-signals chạy ~8 phút, interval 5 phút → 2 jobs overlap, cùng client_id=1. Transient, các slot sau recover. Fix sau nếu cần: tăng interval lên 10 phút hoặc dùng client_id riêng mỗi slot.

**Pre-flight scheduler — DONE + fail-closed (commits 0f91fc9 + 90a7000 + 8351fd6):**
- Logic: `flag=True` (cả ibkr_daily + spy_csv xong) → run. `flag=False/None` → skip
- `update_ibkr_daily` exit 1 nếu bất kỳ instrument nào fail (Gateway down, 0 bars)
- Không có loophole: không guess từ parquet-only, không chạy khi không chắc

**⚠️ Scheduler — giới hạn máy cá nhân:**
- CHỈ chạy khi process sống. Sleep/reboot → không tự phục hồi
- Cần sống lúc 09:31 ET (maxhold) và 13:45 ET (pre-flight)
- **Routine sáng:** (1) Check scheduler còn sống → nếu không: `pythonw -m global_index.run_scheduler --port 4002` TRƯỚC 13:45 ET; (2) `check_next_entry.py`

#### Thứ tự tiếp theo
~~P0c~~ ✅ DONE → **P1** (dry-run scheduler 1-2 ngày liên tục, không cần verify tay) → P2 (order thật, theo dõi đêm đầu) → C1 slippage vs 2-tick → nhiều tháng → VPS/ops → live 1 micro.

**P1 ✅ DONE 2026-07-30** — 30 giây, start + đọc log + kill:
```
25 jobs: maxhold_exit(09:31) + preflight(13:45) + live_day(14:05) + continuous 14:10→15:55
Scheduler TZ: America/New_York ✅  Port: 4002 ✅  dry-run: True ✅  Không lỗi.
```
→ **P2 là bước tiếp theo** (bật scheduler không --dry-run, order thật)

### Next steps (IBKR ACCOUNT APPROVED → PAPER)

**Thứ tự implement:**
- [x] 1. Wire `IBKRBroker._fetch_raw()` → P2 fixed; C6/C3 đã test offline; `connect_test_paper.py` cho live test
- [x] 2. Wire `IBKRBroker.send_order()` → **LIVE VERIFIED 2026-07-08** (17/17 PASS incl. orders)
      outsideRth=True required: futures 23h/day, IBKR's preset forces TIF=DAY → cancel nếu không set flag
      Error 10349 = INFORMATIONAL (not fatal) — ib_insync log "Canceled order" nhưng order vẫn fill
      Fill time: 0.26s entry / 0.15s exit (design assumption 5s → 20× faster than assumed)
      Slippage: 1 tick round-trip. Price dev 0.07% vs last bar. A1/A4 PASS.
      A2 partial / A3 timeout chưa test (cần inject reject/timeout — để GIAI ĐOẠN 2b khi cần)
      Log noise fixed: ib_insync.errorEvent.clear() + custom handler; 2109/10349/2174 → DEBUG
- [x] 3. Wire `IBKRBroker.get_positions()` → **LIVE VERIFIED 2026-07-08** (11/11 PASS)
      ib.positions() → BrokerPosition list. CON.3 PASS: n_positions=1 [(MES, LONG, 1)]
      B3 cross-check in runner.py: so sánh file state vs broker on startup; CRITICAL nếu mismatch/orphan
      NOTE: paper account còn open 1 MES LONG từ test — cần close trong Gateway trước khi live
- [x] 4. Wire `_handle_rollover()` → **CODE DONE 2026-07-08** (live verify pending Sep 11 roll)
      CLOSE front_month + OPEN next_month, same polling pattern as send_order()
      3 outcomes handled: (FILLED,FILLED)=log slippage / (FAILED,*)=position unchanged /
      (FILLED,FAILED)=position flat → remove from state + CRITICAL
      _handle_rollover_if_needed() in runner: runs before fetch_bars each day (no-op if not roll date)
      MockBroker: _roll_fn=None → skip; test path: synthetic FILLED fills; 14/14 offline PASS

**Trước paper:**
- [x] [A5] Parquet gap filled — Databento LIVE VERIFIED 2026-07-08:
      All 5 instruments updated through 2026-07-07 (2024-12-01→2026-07-07, overlap 30d)
      Splice offset applied (diff back-adjust re-anchored Dec2024→Sep2026)
      Daily mỗi sáng: python -m global_index.update_ibkr_daily (IBKR ContFuture)
      Files: global_index/update_futures_data.py, global_index/update_ibkr_daily.py
- [x] [D1] ĐO: deploy_sim --end 2024-12-31 trên *_8y.parquet đã A5 = $53,172 ≠ $52,936
      ROOT CAUSE CONFIRMED: contamination = overlap window replacement (Dec 2024 bars), KHÔNG phải constant offset
      Constant offset: ATR/P&L không đổi (math proven). Thủ phạm: 30-day overlap bars replaced by new_adj anchor mới.
      $53,172 = số NHIỄM. KHÔNG lock. Phải khôi phục $52,936 via re-fetch.
- [x] [D2] Frozen parquet DONE: --full-refetch --end 2024-12-31 (Databento 2 API keys)
      5 files: ES/NQ/YM/RTY_frozen_2024.parquet + NKD_frozen_2024.parquet (2024-12-30 end)
      Staged tại data/cache/futures/frozen_sim/ (renamed *_8y.parquet cho deploy_sim)
      Deploy run 1: net=$53,021 / Calmar=3.07 / MaxDD=$2,501 | Run 2 (reproducibility): BYTE-IDENTICAL ✓
      $52,936 NON-REPRODUCIBLE (incremental artifact). $53,021 = clean ground truth.
      Fit_A floor trên frozen: $51,459 / Calmar=2.69 (thay thế stale 2.38). floor/baseline=87.6% ✓
- [x] [D3] INVARIANTS.md updated: baseline=$53,021/Calmar=3.07, floor=2.69, vault floors re-checked (3.33/2.99 > 2.69 ✓)
      ISSUES_LOG I5.5 → RESOLVED. SCRATCHPAD updated. frozen/live split documented.
- [ ] **B4 [DECISION: Option B]** Confirm NKD CME bundle + Rule 576 cert → add NKD sau cert. Paper phase 1 = swing-only (MES/MNQ/MYM/M2K + STRESS_MID). So sánh paper P&L vs swing-only IS subset, KHÔNG full $53,021.
- [ ] runner.dump_state(): điền Group B (slippage, fill quality, paper-vs-backtest, health)
- [ ] update_spy_csv timing: run trước runner, không intra-session (I5.4)

**TRƯỚC LIVE (sau paper, có data mới):**
- [x] 6. Build cơ chế re-freeze GĐ3 (Phần A: code + test giả lập) — 40/40 PASS
- [ ] 6b. Re-freeze lần 1 thật: chạy refreeze_hmm với data mới khi có (sau 2025)
- [ ] 7. Vault 2025 test với fit cuối

**RÀNG BUỘC:**
- Sửa HMMEngine class → đụng cả stocks pipeline — verify cả hai (futures + raits/backtest) trước khi commit

### Pending: File cleanup (cân nhắc sau)
Đề xuất xóa (user duyệt — đã verify 3 cách, an toàn vì trong git history):
- d:\raits\part3_costs.txt      ~1.3MB scratch (NKD cost debug output)
- d:\raits\part3_costs2.txt     ~1.3MB scratch
- d:\raits\part3_debug.txt      ~1.3MB scratch
- d:\raits\part3_final.txt      ~1.3MB scratch
- d:\raits\debug_vault_labels.py        one-off Gate-5 debug, resolved
Giữ lại: baseline_fit_c.txt, baseline_deploy_sim.txt, nkd_fit_verify.py
reconcile_gd0 không ảnh hưởng: phiên này 0 file production bị sửa.

### Key decisions
- mult=2.5 for ALL clusters (roska4_swing, roska4_stress, global_nkd) — matches deploy_sim defaults
- daily_atr_series from futures._validated_core shared by deploy_sim and signal_layer (identical impl in both)
- MockBroker realizes pnl from backtest ledger (not bars) for apples-to-apples vs deploy_sim
- FuturesRunner.state.breaker must be set manually after construction to match deploy_sim
- HMM fit_C (2024-12-31) is paper baseline; fit_A (2022-12-31) kept as conservative degradation floor
- Re-freeze gate: run hmm_sensitivity_gate.py annually; approve if label change <5%, investigate if >5%

### Files touched
global_index/signal_layer.py (risk_sized fix: to_candidate new signature, _asof_naive, ROSKA4_MULT/NKD_MULT)
global_index/broker.py (new — MockBroker + Order/Fill/BrokerPosition + Broker ABC)
global_index/runner.py (new — FuturesRunner, run_day, run_history)
futures/reconcile_nkd.py (new — Phase 1+2 reconciliation, committed f9d3f98)
futures/basket.py (hmm_fit_end 2022→2024)
global_index/regime.py (hmm_fit_end default 2022→2024, docstring updated)
global_index/deploy_sim.py (hmm_fit_end default 2022→2024)
global_index/generate_replay_snapshots.py (REGIME indirection for NKD labels, was hardcoded 2022)
futures/backtest_combined.py + futures/backtest_system.py (annotated harness)

---

### Completed
- [x] Extended IS from 3yr (2020-2022) → 6yr (2017-2022), $50k account
- [x] Fix BacktestConfig orphaned fields (max_position_pct, kelly_fraction not wired)
- [x] max_risk_pct 1% → 1.5% (VolTarget constraint)
- [x] kelly_fraction 0.5 → 0.75 (3/4 Kelly) → P&L +37%
- [x] PE_SHORT_GAP_MIN confirmed at 5%
- [x] MAX_TREND 2 → 3 → +$3,158 (+11%), ann 9.4%→10.5%
- [x] Bootstrap per strategy (10,000 iterations) — FADE/GAP_FILL/VWAP_MR no edge confirmed
- [x] Remove FADE + GAP_FILL + VWAP_MR from engine._REGIME_STRATEGIES
- [x] Fix VWAP_MR zombie (engine section 8 bypassed _REGIME_STRATEGIES via _vwap_mr_vol_ok gate)
  - Added `_vwap_mr_regime_ok` check → 0 VWAP_MR trades confirmed (snapshots 151115, 152940, 155030)
- [x] max_position_pct 0.30 → 0.40
  - TF: Kelly-bound at 21%, unaffected
  - ORB: switches from PosLimit ($15k) to Kelly ($16,900) → +12.7% per trade
  - STRESS_MID, PE_SHORT: also benefit (were PosLimit-bound)
- [x] Full data coverage audit:
  - CANDIDATE_POOL (37 stocks), PHASE1, PHASE2, QQQ, IWM: 2017-2024 ✓
  - META: 2021-2024 only (missing 2017-2020) → fetch in progress
  - PE_EXPANSION (25 stocks): 2019-mid2024 (missing IS 2017-2018 + OOS tail 2024) → fetch in progress
  - Sector ETFs (XLF, XLE...): 2023-2024 only → fetch in progress (fetch_sector_etfs.py)

### Current baseline — LOCKED (post PE_EXPANSION fetch)
- **Snapshot: results_20260624_200216.pkl**
- **Settings: IS 2017-2022 | $50k | 1.5% risk | 0.75K | MAX_TREND=3 | 5% PE gap | max_pos=0.40 | zombie fixed**
- **Total: +$34,214 | Calmar~1.55 | VWAP_MR=0 trades**
- Year: 2017=+$2,156 | 2018=+$7,427 | 2019=+$655 | 2020=+$9,601 | 2021=+$5,614 | 2022=+$8,761
- Strategy: ORB=$5,910 | TF=$16,191 | PE_SHORT=$6,888 | STRESS_MID=$3,290 | STRESS_ORB=$1,734 | GF_SHORT=$203
- NOTE: META still missing 2017-2020 (FB ticker issue). Sector ETFs pending (for VWAP_MR re-eval only).
- PE_EXPANSION effect: net -$226 (2018 bad trade -$753 outweighs 2017 gain +$527)

**Prior baseline (results_20260624_135619.pkl):** +$31,484 | Ann: 10.5% | 1,878 trades (with FADE/GAP_FILL/VWAP_MR)

### Completed (paper-trading harness)
- [x] **Phase 1 DONE**: Paper-trading harness skeleton — broker/reconciliation/runner, 75 tests
  - MockBroker: slippage/partial/reject/latency, seed RNG
  - ReconciliationLog: CSV+JSONL, analyze() with p90 latency/slippage
  - PaperTrader: DISCIPLINE_LOCK, PAPER_ONLY, KILL_SWITCH discipline guards
- [x] **Phase 2 DONE**: ReplayContextFeed — replicates engine_refactored's BarContext field-by-field
  - context_feed.py builds identical BarContext per bar: universes, VIX gates, spy_or_high/low,
    day_stocks, spy_history, HMM state, cur_vol, fade_atr_top2, pe_short_calendar
  - Verified on full IS 2017-2022: **116926/116926 bars identical** (incl. hmm_state, cur_vol)
  - Circuit breaker bars gracefully excluded via bar_ts pairing
  - PE_SHORT ticker injection (decide() mutates day_stocks) tolerated as expected extra_engine

### Completed (Gap 1 investigation — 2026-07-04)
- [x] **Gap 1 CONFIRMED + DOCUMENTED**: LivePolygonFeed vs ReplayContextFeed — 9/604 trades diverge on exit_price
  - Root cause: `day_stocks[ticker].iloc[-1]` in CB (`runner.py:629`) and SAFETY_MODE (`decision_unit.py:234`) assumes full-day data
  - ReplayContextFeed: `day_stocks` pre-loaded full day → `iloc[-1]` = 15:55 bar (look-ahead bias)
  - LivePolygonFeed: `day_stocks` incremental → `iloc[-1]` = trigger bar T (correct live semantics)
  - Full `iloc[-1]` / full-day-assumption scan: 3 UNSAFE (all in CB/SAFETY_MODE exit path, all known); all others safe
  - Backtest net PnL on 9 affected trades: -$340.88. Live P&L quantification pending (re-run verify_live_path.py --live-feed --full --costs)
  - Engine/decision_unit NOT modified (per constraints); gap is backtest look-ahead, not a live bug
  - Files created: `GAP1_REPORT.md` (full 4-step root cause), `KNOWN_DIFFERENCES.md` (known divergence registry with full iloc[-1] scan appendix)

### Completed (Gap 1 live P&L quantification — 2026-07-04)
- [x] Full IS `--live-feed --costs` run complete: exactly 9 trades diverge, nothing else
  - Live net PnL on 9 trades: -$653.60 vs backtest -$340.88 → backtest optimism +$312.72 (~2% of $15,952 IS)
  - Largest: QQQ STRESS_MID SAFETY_MODE sign flip (+$286.92), VRTX ORB SAFETY_MODE (+$123.45)
  - KNOWN_DIFFERENCES.md KD-001 updated with measured numbers

### Completed (Phase 3 + LivePolygonFeed — 2026-07-02)
- [x] **Phase 3 DONE**: End-to-end PaperTrader with ReplayContextFeed — 604/604 trades identical, costs on, net P&L $15,926.85 == $15,926.85 to the cent
  - Bugs fixed: half-day EOD close, END_OF_PERIOD, CB integration, PE_SHORT EOD exclusion (ALL, not same-day), same-bar exit for intraday, SPY spy_bar source (ctx.spy_bar not day_stocks["SPY"])
- [x] **LivePolygonFeed DONE**: real-time Polygon WebSocket BarContext feed (raits/live/context_feed.py)
  - _BarAccumulator: thread-safe, late/OOO bars sorted, duplicates last-write-wins, missing bar = absent
  - _iter_test (test mode): replays _test_market_data incrementally, all non-day_stocks fields byte-identical to ReplayContextFeed
  - _iter_live (live mode): Polygon WebSocket (lazy import), background thread, exponential backoff reconnect (1→2→4→8→16→30s), day-level context from daily_data
  - day_stocks is incremental in live mode (bars up to bar_ts only) — correct live semantics; spy_or converges after 9:44
  - 49/49 tests pass (raits/tests/live/test_context_builders.py)

### Completed (LivePolygonFeed smoke test — 2026-07-03)
- [x] **IBKRBroker complete**: connect/disconnect lifecycle, connection-guard ordering (check before lazy import), submit_order fill-poll, cancel_order stub, account_equity via NetLiquidation
  - 8 tests pass (test_live_broker.py): lazy import, connection guard, error message, disconnect-when-not-connected safe
- [x] **test_live_runner.py fixes**: pre-existing bugs fixed (_intent_to_trade now requires bar_ts; _check_exits mock; recon.analyze() missing key)
  - Added: test_live_polygon_feed_wires_into_paper_trader, test_live_feed_all_guards_clean_run
  - 117/117 tests pass (all raits/tests/live/)
- [x] **Reconnect/backfill tests** (raits/tests/live/test_reconnect_backfill.py): 12 tests
  - A/B: backoff delay math, d_idx reset
  - C-F: _backfill_bars REST call, enqueue, full-fail logger.error, partial-fail, polygon-not-installed warning
  - G: backfill_on_reconnect flag stored
  - H: WS thread reconnects after exception (integration test — root cause was wrong epoch ms: 1641214200000→1641220200000 for 09:30 ET)
  - I: _backfill_bars called after reconnect with correct from_ts
- [x] **context_feed.py**: _backfill_bars method (REST gap fill), _last_bar_ts closure, backfill wired after reconnect sleep; pd.Timestamp.utcnow() → .now("UTC") deprecation fix
- [x] **ws_handshake_test.py** (raits/live/scripts/): off-hours connection/auth/subscribe test — checks connection open, connected status, auth_success, AM.SPY subscribed, clean disconnect; exit 0/1
- [x] **live_smoke.py** (raits/live/scripts/): market-hours feed observation — logs every bar, prints summary + pass/fail checklist; --minutes N configurable; no orders placed

### Completed (Refreeze GĐ3 anchor fix + Sizer Guard — 2026-07-07)
- [x] futures/refreeze.py: anchor default fix `2018-01-01` → `2017-01-01` (CLI + was wrong default causing Calmar 2.49 vs 2.744)
- [x] futures/refreeze.py: FreezeRecord.invalid field + rollback() skips invalid entries (last-valid semantics)
- [x] futures/test_refreeze.py: T12 rollback tests (8 cases T12.1-T12.8: skip-invalid, audit trail, from_dict backward compat)
- [x] global_index/deploy_sim.py: `--n-contracts` flag, sizer guard WARNING (--start/--end without pin), NKD hardcoded n=1, labels on full bench before clip
- [x] global_index/generate_replay_snapshots.py: NKD structural n=1 fix (cb_map["MNKD"] = 1)
- [x] docs/futures/STATUS.md: fix stale "40/40 PASS" → "~76/76" + new section Sizer Guard + NKD Structural Fix
- [x] docs/futures/DECISIONS.md: added NKD hardcoded n=1 decision entry
- [x] Regression confirm: ALL PASS (2026-07-07) — baseline $52,936/Calmar 2.744 intact, 4 reconcile PASS, all test suites PASS

### Completed (Bug Sweep Round 2 — 2026-07-07)
- [x] CAT 1: Live decision path — pnl_sized là pattern duy nhất live≠backtest. Exhaustive grep xác nhận. H4 là fix đúng và đủ.
- [x] CAT 2: Exec path — I4.8 mới: position removed from state BEFORE CLOSE sent, Fill discarded. _retry_pending_exits() không tồn tại (grep: 0 matches). IBKR-gated (A1-A5).
- [x] CAT 3: State restart — peak/day_start/cur_day/exit_day persist đúng. Stale-file window 265s documented (B3 gap). HALT persists correctly via peak_equity.
- [x] CAT 4: n=2 config — code đúng về logic (NKD hardcoded n=1, Rổ4 n=n_contracts). CHƯA run end-to-end. Command: `python global_index/deploy_sim.py --n-contracts 2`.
- [x] CAT 5: Reconcile edge — backtest coverage đầy đủ (2018-2024 includes all rolls/COVID). Live roll handling = IBKR-gated (I5.2), không phải reconcile gap.
- [x] CAT 6: Systematic live vs backtest grep — không phát hiện pattern ẩn ngoài pnl_sized.
- [x] Docs: `docs/futures/BUG_SWEEP_R2.md` (new), `docs/futures/ISSUES_LOG.md` I4.8 (new)

### Completed (H4 fix: HALT_DAY equity sync — 2026-07-07)
- [x] Bug sweep H4: HALT_DAY mù intraday → root cause confirmed (state.equity không sync từ broker trong session)
- [x] H4 fix in `global_index/runner.py`: sync `state.equity = broker.get_equity()` sau CLOSE loop, trước OPEN entries
      MockBroker: delta ≈ 0 → no-op (backwards-compatible). IBKRBroker live: syncs real fills → HALT_DAY hoạt động.
      Residual gap: STRESS_MID (same-session, decide_day atomic) — tác động thực tế nhỏ.
- [x] T29 test added to `global_index/test_operational_fixes.py`:
      T29.1: no OPEN orders when daily loss ≥ 4% → PASS
      T29.2: HALT_DAY event emitted → PASS ("BREAKER HALT_DAY: daily loss 4.2% — entries blocked today")
      116/116 ALL PASS (full suite)
- [x] Docs: ISSUES_LOG.md I4.6 (H4 root+fix+classify) + I4.7 (C1-EXIT accepted, low)
- [x] OPEN_QUESTIONS.md: H4 là điều kiện cứng pre-live (PREREQ, đã fix)
- [x] STATUS.md: Operational fixes → 116/116 PASS, H4 documented

### Completed (Session wrap-up + full doc consolidation — 2026-07-07)
- [x] docs/futures/ISSUES_LOG.md: nhật ký 22 vấn đề (6 nhóm), verify code + nguồn thật
      I1 Data Integrity (CSV bug, live divergence)
      I2 HMM/Regime (anchor bug, contamination, rollback, C2 doc, equity restart)
      I3 Sizing/Validation (sizer n=3, NKD sizing, $82k threshold, vault verdict sleeves)
      I4 Ops Safety (16 cơ chế grep-verified, WARN dead, same-day phases, B1, J2)
      I5 Wire pending (fill handling, rollover, D5/F3, spy_csv timing)
      I6 Docs (SYSTEM_MODEL, CROSS_SYSTEM)
- [x] docs/futures/LESSONS.md: 9 bài học meta từ lỗi thật
      L1 data self-consistent ≠ correct | L2 grep verify completeness | L3 bug ẩn non-default config
      L4 estimate ≠ measurement | L5 "passed" ≠ correct setup | L6 per-sleeve verdict
      L7 no fabrication | L8 rollback = last valid | L9 contamination → path-dependent metrics
- [x] docs/README.md: thêm SYSTEM_MODEL/VISUALIZE/ISSUES_LOG/LESSONS/CROSS_SYSTEM; thêm "khi nào đọc" rows
- [x] docs/futures/STATUS.md: thêm "System Model + Cross-System Docs" block

### Completed (Cross-system analysis + futures model docs — 2026-07-07)
- [x] docs/futures/SYSTEM_MODEL.md: full 4-dimension model (Control Flow, Data Flow, Safety, State)
      16 safety mechanisms verified via grep, CHIỀU 3 intervention order table (17 rows incl C2)
- [x] docs/futures/VISUALIZE.md: 4 ASCII tầng (system map, data flow, safety layers, state lifecycle)
- [x] 4 issues reviewed from SYSTEM_MODEL:
      F1 — C2 missing from intervention diagram → FIXED in both docs
      F2 — equity restart two-source → VERIFIED CORRECT: broker is source-of-truth, B1 persists peak separately
      F3 — same-day order phases → CLARIFIED: nested per-entry (not all-OPEN then all-CLOSE)
      F4 — WARN dead field → DOCUMENTED INTENTIONAL (circuit_breaker.py:19)
- [x] docs/CROSS_SYSTEM_FINDINGS.md: futures findings classified → stocks code verified for each
      Adjustment: stocks path already tracked in stocks/OPEN_QUESTIONS.md
      HMM contamination: CLEAN (initial fit < _bt_start; vault excluded via _slice_before; retrains causal)
      Annual refreeze gate: GAP — stocks has per-retrain validation only, no formal gate
      State persistence: NOT APPLICABLE — stocks is paper-only (LiveContextFeed NotImplementedError)
- [x] docs/stocks/OPEN_QUESTIONS.md: 2 new entries added (refreeze gate, state persistence)

### Completed (Futures Script Inventory + Pipeline Docs — 2026-07-06)
- [x] SCRIPT_INVENTORY.md created: 53 scripts classified (global_index/ 35 + futures/ 18)
      Production manifest traced from runner.py run_day() import chain
      SUPERSEDED / ANSWERED / RESEARCH / TEST / PRODUCTION / DATA-PREP / BACKTEST / PRODUCTION-PLANNED
- [x] PIPELINE_FLOW.md created: run_day() fully traced step-by-step
      Exact execution order (D5 kill-switch → fetch → signal → stale-guard → exits → decide → exec → persist)
      ASCII data flow diagram, sleeve activation table, 5 non-obvious observations

### Completed (Futures Script Cleanup — 2026-07-06)
- [x] 14 non-production scripts archived (reversible — moved to _archive/, NOT deleted)
      Superseded → `_archive/superseded/`: futures/backtest_system.py, futures/net_exposure.py
      Answered research → `_archive/answered/`: combined.py, combined_system.py, wfo.py, vault.py,
        scaling_dd_trust.py, stress_mid_trust.py, hmm_flip_year_trust.py,
        risk_diagnostic.py, hold_vs_entry_diagnostic.py, reject_diagnostic.py,
        reject_value_diagnostic.py, priority_sweep.py
- [x] ARCHIVE_LOG.md created: docs/futures/ARCHIVE_LOG.md — reason + replacement per script
- [x] SCRIPT_INVENTORY.md updated: ARCHIVED status for all 14 moved scripts
- [x] Production chain verified: no production files import any archived scripts

### Completed (Futures SYSTEM_EXPLORER + GLOSSARY — 2026-07-06)
- [x] docs/futures/SYSTEM_EXPLORER.html: 9-step interactive pipeline explorer (self-contained)
      PRE/01-08 steps: files + logic + non-obvious notes + pending (OFFLINE/IBKR/PAPER) + decisions
      Tabs: Pipeline view, Tất cả TO-DO (grouped by blocker), Tìm file (search), Glossary
- [x] docs/futures/GLOSSARY.md: mọi mã nội bộ A–J, UT-1–6, KD-001, fit_A/B/C, calm-flip
      Groups: Guards, Exception Safety, State/Restart, IBKR specs, UT, HMM/Regime, naming collisions
      Nguồn: trích từ code/docs (file:line), không đoán
- [x] SYSTEM_EXPLORER Glossary tab: renderGlossary() + naming collision table
- [x] SYSTEM_EXPLORER tooltips: wrapCodeRefs() adds hover tooltips trên mọi mã trong step text
- [x] docs/README.md updated: GLOSSARY.md added to directory tree

### Next steps (ordered)
- [x] PE_EXPANSION (25 stocks): 2017-2024 ✓ fetched
- [x] window_debug --rebuild → baseline 200216 ($34,214). PE_EXPANSION net -$226 (2018 bad trade)
- [ ] Fetch FB (META pre-rename) + sector ETFs → rebuild again for complete baseline
- [ ] Run vwap_mr_etf_sim.py (after ETF data ready) → re-evaluate VWAP_MR on proper universe
  - If p<0.05 and P&L positive → re-add permanently; else removal confirmed
- [ ] Run WFO (wfo_real_run.py) — params 15/2.0/30 are stale, engine changed significantly
- [ ] After WFO: update configs/final_params.yaml with new optimal params
- [ ] Run final snapshot post-WFO as pre-OOS baseline
- [ ] Fetch OOS 2023-2024 5-min data if needed
- [ ] OOS vault test — run ONCE, no iteration

### Completed (refactor gate)
- [x] **Gate 1 PASSED**: RefactoredBacktestEngine byte-identical to BacktestEngine on IS 2017-2022
  - 604 == 604 trades, 100% field match, P&L diff $0.00
  - Bug A: PE_SHORT inject wrote local copy (discarded) → fixed to mutate ctx.day_stocks in-place
  - Bug B: Same-bar entry+exit missed (pending_entries not in ctx.open_trades) → fixed with post-open _check_exits call in engine_refactored
  - Bug C: SAFETY_MODE exit price used loc[bar_ts] (current bar) vs engine.py iloc[-1] (last bar of day) → fixed in decision_unit.py §4

### Completed (CB fix implemented — 2026-07-08)
- [x] **CB FIX IMPLEMENTED — both engines corrected; verification pending (user runs script)**

  **Changes made:**
  - `engine.py` `_close_all()`: added `circuit_breakers=None, update_cb=False` params. When `update_cb=True`, calls `circuit_breakers.record_trade_result(trade.net_pnl or 0.0)` after each close. Daily-drawdown-CB call sites (lines 1569+1578) now pass `update_cb=True`. SAFETY_MODE and EOD unchanged.
  - `engine_refactored.py` `_close_all()`: identical change.
  - `engine_refactored.py` bar loop: SAFETY_MODE ExitIntents NO LONGER committed via `_close_trade()`. Instead, when `override_active=True`, calls `_close_all("SAFETY_MODE", skip_tf=True)` (bypasses CB) and `continue`. Matches ORIG section-4 behavior exactly.
  - Stale ORIG cache deleted: `data/cache/verify_orig_trades_IS.pkl`

  **VERIFIED 2026-07-08:**
  ```
  ORIG == REFAC: 605 trades | P&L $15,019.79 | diff $0.0000  ✓
  ```
  Daily-CB events in IS: 13 days fired, 10 positions actually closed (3 days had 0 open at CB bar).
  New baseline = 605 trades (+1 vs old 604). The SAFETY_MODE fix in REFAC unblocked 1 trade that REFAC's
  over-counting had been blocking; this outweighed the daily-CB counting's additional blocking.
  New baseline committed: `data/cache/verify_cb_fixed_baseline.pkl`

### Completed (CB semantics analysis — 2026-07-08)
- [x] **CB SEMANTICS FULLY ANALYZED — fix plan written, code not yet changed**

  **Issue 1 — Correct CB vs what each engine does:**
  ORIG is 4/5 correct: correctly skips SAFETY_MODE + EOD, correctly counts STOP/TARGET/TIME_STOP. Wrong only for daily-drawdown-CB (should count, both engines miss it via `_close_all("CIRCUIT_BREAKER")`).
  REFAC is 3/5 correct: also misses daily-drawdown-CB AND over-counts SAFETY_MODE (via ExitIntents→`_close_trade`). **Neither engine is fully correct. ORIG is closer.**
  
  Prior CB_INVESTIGATION.md error corrected: claimed "REFAC marginally better for daily-CB" — FALSE. Both engines call `_close_all("CIRCUIT_BREAKER")` (ORIG:1569, REFAC:810), both miss daily-CB.

  **Issue 2 — Quantification on Parquet IS data:**
  Diff = 1 trade: CVX TF 2019-01-18 14:00, pnl=-$208.09. ORIG IS worse by $208.09 (extra loser).
  Stress-concentrated: YES — triggered by SAFETY_MODE on 2019-01-03 (post-Q4 2018 bear market).
  On window_debug (the actual validated baseline): 604==604 byte-identical → principle "deploy==validated" is satisfied on the validated dataset.
  On live Parquet data: REFAC more conservative (halts earlier in stress) — protective direction.

  **Issue 3 — Fix plan (before paper):**
  Add `update_cb` flag to `_close_all()` in both engines. Pass `update_cb=True` only for `"CIRCUIT_BREAKER"` reason (daily-drawdown-CB). In REFAC, route SAFETY_MODE exits through `_close_all()` instead of `_close_trade()`. Re-run IS → new ORIG==REFAC baseline → validated==deployed.
  Full implementation details in `docs/stocks/CB_INVESTIGATION.md` Issues 1-3 sections.

### Completed (605 vs 604 root cause — 2026-07-08)
- [x] **ROOT CAUSE CONFIRMED**: `_close_all()` never calls `record_trade_result()` in ORIG; REFAC does.

  In ORIG (engine.py): `_close_all()` → `trade_log.close_trade()` directly. Never calls `_close_trade()` → never calls `circuit_breakers.record_trade_result()` → CB streak unchanged for any SAFETY_MODE/EOD close.

  In REFAC (engine_refactored.py): SAFETY_MODE → `decide()` ExitIntents → `_close_trade()` → `record_trade_result()` called → streak updated.

  **Trigger day: 2019-01-03**. SAFETY_MODE (or EOD) fires in window_debug run, closing QQQ STRESS_ORB, IWM STRESS_ORB, SPY STRESS_MID via `_close_all()`. Confirmed: instrumented run of ORIG shows zero [BEFORE/AFTER] output for Jan 3 (all exits bypassed `_close_trade()`).

  **Divergence**: ORIG enters Jan 18 with consec=3; REFAC with consec=4.
  **Jan 18 09:30**: MMM TREND_FOLLOW closes (pnl=-$230.37).
  - ORIG: 3→4 < 5 (CB limit) → bar loop continues → CVX TF LONG enters 14:00 → **605 trades**
  - REFAC: 4→5 = CB limit → `_circuit_breaker_active=True` → bar loop breaks at 09:35 → no CVX → **604 trades**

  This is a deliberate architectural difference, not a bug. The 604==604 gate passed on ORIG's full IS Parquet baseline vs REFAC replication of that same run; the 605 vs 604 discrepancy only appears when SAFETY_MODE fires differently across data sources (window_debug vs Parquet).

  **Diagnostic scripts** (raits/raits/scripts/):
  - diagnose_cvx_entry.py, diagnose_streak_stateful.py, diagnose_orig_jan18.py
  - diagnose_jan3_ordering.py, diagnose_jan3_engine_order.py

### Completed (Bootstrap Audit — 2026-07-08)
- [x] **ISSUE 1 CLOSED**: Fresh verify_parallel_run.py --reset-orig-cache = 605 trades / $15,019.79
      IDENTICAL to current engine. Stale cache (verify_orig_trades_IS.pkl) was the source of 604.
      No unexplained drift. Investigation closed.
- [x] **ISSUE 2 — Continuous IS bootstrap**: bootstrap_continuous.py committed + run
      2 hard flips: ORB (CONFIRMED → NO EDGE, p=0.329), STRESS_ORB (CONFIRMED → NO EDGE, p=0.215)
      TF partial: CONFIRMED → BORDERLINE (p=0.116). PE_SHORT holds (p=0.011).
      Saved: raits/configs/bootstrap_continuous_report.txt
- [x] **Bootstrap soundness audit**: diagnose_bootstrap_soundness.py committed + run
      IID method consistent (both YbY and continuous). Bias direction: optimistic (true p higher).
      TF N-control: breakeven N ~1,500 (4x actual) — per-trade edge genuinely weaker, not just N.
      YbY TF: Cohen's d=0.082 vs continuous: 0.063 (23% decline in per-trade quality).
      PE_SHORT jackknife: remove top 2 trades → p=0.055 (BORDERLINE). Top 3 = 58% of P&L. Fragile.
      IS annualized return: 5.0% on $50k — thin. Honest read: edge marginal on correct design.
      Saved: raits/configs/bootstrap_soundness_report.txt
- [x] **BOOTSTRAP_AUDIT.md written**: docs/stocks/BOOTSTRAP_AUDIT.md — full audit record
- [x] **diagnose_removed_strategies.py committed + RUN** (FADE/GAP_FILL/VWAP_MR continuous IS)
      Script patches _REGIME_STRATEGIES + use_fade_scanner=True, runs engine (~35min), IID+block bootstrap+jackknife
      Results:
        FADE    (N=199): IID p=0.997, block p=1.000 → removal-correct (actively losing: WR=33.7%, mean=-$32.53/t, t=-2.87)
        GAP_FILL (N=16): IID p=0.100, block p=0.000* → uncertain-needs-OOS (* ARTIFACT: N<block_size → degenerate)
          Jackknife k=1: p=0.167 (NO EDGE). Top 3 trades = 80% P&L. N=16 untestable.
        VWAP_MR (N=33): IID p=0.889, block p=0.998 → removal-correct (WR=24.2%, mean=-$1.54/t, t=-1.23)
      Saved: raits/configs/removed_strategies_report.txt

### Verdict: Bootstrap Audit (CLOSED)
- 605/$15,019.79 IS the correct baseline (stale cache confirmed).
- FADE/GAP_FILL/VWAP_MR removals: all stand on continuous design.
  FADE and VWAP_MR: definitively removed (negative edge). GAP_FILL: untestable (N=16) but not confirmable.
- Strategy inclusion decisions were made on YbY design (wrong). On continuous (correct) design:
  ONE confirmed (PE_SHORT, concentrated N=29), ONE borderline (TF, IID-optimistic p=0.116), TWO NO EDGE in system (ORB p=0.329, STRESS_ORB p=0.215).
- Do NOT re-cut active strategies on IS. Do NOT re-add removed strategies on IS. 2025 OOS is the real arbiter.

### Completed (R-multiple + Block Bootstrap — 2026-07-08)
- [x] **bootstrap_normalized.py** committed + run: R = net_pnl / (shares x |entry_price - stop|)
      TF: dollar p=0.116 -> R-p=0.009 CONFIRMED (delta=-0.107; dollar understated early-equity wins)
      PE_SHORT: p=0.011 -> R-p=0.010 CONFIRMED | ORB/STRESS_ORB/STRESS_MID: NO EDGE =
      GF_SHORT: MeanR=8.59 flagged as artifact (see below)
      Saved: raits/configs/bootstrap_normalized_report.txt
- [x] **GF_SHORT artifact confirmed**: CSV `stop` = FINAL trailing chandelier stop (not initial risk).
      engine.py:1529-1540 trails stop down per bar -> profitable shorts end with tiny |entry-stop|.
      COST: entry=490.420, final_stop=490.229 (below entry for SHORT) -> fake risk=$1.33 -> R=+37.73.
      TF CLEAN: 0/353 wrong-side stops -> TF R-multiple is conservative, not inflated.
      GF_SHORT R verdict WITHDRAWN. Reverts to dollar IID p=0.010 (N=12, untrustworthy size).
- [x] **bootstrap_block_r.py** committed + run: circular block bootstrap B20/B40
      TF: B20 p=0.012 CONFIRMED (survives path-dependency). PE_SHORT: B20 p=0.009 CONFIRMED.
      GF_SHORT degenerate (N=12<20). ORB/STRESS_ORB/STRESS_MID: NO EDGE.
      Saved: raits/configs/bootstrap_block_r_report.txt
- [x] **Final honest edge picture (4 filters: IID-dollar | IID-R | block-R | JK-R)**:
      TF: CONFIRMED robust (all 4). PE_SHORT: CONFIRMED concentrated (top-5=75% CumR; JK k=3 borderline).
      GF_SHORT: UNTRUSTWORTHY (R artifact + N=12 degenerate). ORB/STRESS_ORB/STRESS_MID: NO EDGE.
      Pre-committed 2025 OOS criteria written in BOOTSTRAP_AUDIT.md.
- [x] **Vault OOS jackknife BLOCKED**: 5-min parquets max 2022-12-30; vault data lost (snapshot overwritten).
      Requires ~2h Polygon re-fetch. Deferred.
- [x] **BOOTSTRAP_AUDIT.md updated**: GF_SHORT root cause, TF validation, 4-filter table, OOS criteria.

### Key decisions
- OOS is one-shot -- do NOT run until engine is fully locked and WFO complete
- VWAP_MR removal may need re-evaluation: was trading stocks (wrong instrument), not ETFs
- STRESS_MID kept (p=0.112, borderline but positive across stress years)
- GF_SHORT kept (n=33 too small to decide; p=0.128)
- max_position_pct=0.40 decided: Kelly-based, ORB/STRESS_MID/PE_SHORT benefit
- Do NOT run WFO until fetch+rebuild complete and true baseline locked
- --use-results-cache INVALID: engine changed (zombie fix), always use fresh run or --rebuild
- OPTIONS IDEA DEAD: BS proxy on 200216 baseline: stock +$34,214 vs option -$257,572 (-852.8%).
  ORB and PE_SHORT benefit (+52k/+121k option edge) but TF/STRESS_MID are catastrophic (-288k/-171k).
  RAITS edge = high-freq small wins; options spread+theta destroys this profile. Skip ORATS.

### Files touched
raits/backtest/engine.py (_REGIME_STRATEGIES, VWAP_MR zombie fix, MAX_TREND=3, PE_SHORT_GAP_MIN=0.05)
raits/backtest/data_types.py (kelly_fraction=0.75)
raits/backtest/wfo.py (max_position_pct added to WFOConfig + _make_config)
raits/raits/scripts/window_debug.py (max_position_pct=0.40)
raits/raits/scripts/wfo_real_run.py (max_risk_pct=0.015, max_position_pct=0.40)
raits/fetch_sector_etfs.py (new — fetch XLF/XLE/etc IS+OOS data)
raits/backtest/engine_refactored.py (Bug B same-bar exit fix)
raits/decision/decision_unit.py (Bug A PE_SHORT inject; Bug C SAFETY_MODE iloc[-1] fix)
raits/raits/scripts/verify_parallel_run.py (orig engine cache + --reset-orig-cache flag)

---

## Sub-task: Futures NO-GO re-examination — correct entry window (2026-07-09)
Status: DONE (ORB + Gap Fill closed with real evidence)

### Context
Hypothesis: futures NO-GO strategies may have been rejected using the stocks-legacy
14:00-15:55 window instead of their own natural window. Investigation found NO prior
rejection record for ORB/gap-fill on futures at all (searched docs/futures/ fully) —
instead found `orb_futures/` (EXPERIMENTAL, never wired to production) with a complete,
never-before-run harness already using market-open windows (09:31-09:45 OR, entries to
15:55). No results were ever recorded anywhere for it.

### Completed
- [x] Confirmed no futures ORB/VWAP_MR-equivalent was ever tested+rejected on 14:00-15:55
      (docs/futures/DECISIONS.md, OPEN_QUESTIONS.md, ARCHIVE_LOG.md, ISSUES_LOG.md — no match)
- [x] Found `orb_futures/` (edge_test.py=ORB breakout, gap_fill.py=fade-the-gap,
      overnight.py=close-to-open hold) — all already use 09:31-09:45 OR + 09:46 entries,
      NOT the stocks 14:00-15:55 window. Marked EXPERIMENTAL, never run before.
- [x] User pushback validated: is 09:30 ET a real futures liquidity anchor, or copied
      from stocks logic? MEASURED (not assumed): avg per-min volume by hour across
      full 23h session, ES/NQ/YM/RTY on frozen_sim data.
      Result: 09:00/10:00/15:00 ET are top-3 volume hours for ALL 4 instruments;
      overnight Globex hours (18:00-08:00 ET) never in top 6 for any instrument.
      CONFIRMS 09:31-09:45 OR window sits in real liquidity, not a stocks-copy assumption.
- [x] Ran edge_test.py (ORB breakout) on frozen_sim + spy_daily_live.csv, cost×1 and ×2:
      POOL 231t, PF=0.67/0.63, net=-$3,883/-$4,441, ALL 7 years (2018-2024) negative both costs.
      DECISIVE NO-GO — not a windowing artifact, real absence of edge at the correct window.
- [x] Ran gap_fill.py (fade-the-open-gap) same data, cost×1 and ×2:
      POOL 100t, PF=0.64/0.58, WR=25%/22%, net=-$1,014/-$1,262, 5/7 years negative.
      DECISIVE NO-GO. Only MNQ marginally positive (25t, +$189) — too thin to matter.
      Both low corr vs swing-TF (+0.002/+0.02) — would have diversified IF profitable.
- [x] Benign note: hmmlearn "Model is not converging" warning appears on every run
      (delta -0.152 on LL~9945, identical across runs — deterministic, tiny relative
      change). Not investigated further — first appearance in this project, likely
      immaterial EM precision artifact, not a blocker for this verdict.

### Verdict
ORB breakout and Gap Fill are real NO-GO on futures Rổ4 at the natural, liquidity-
verified window. Original "wrong window" hypothesis for these two is CLOSED — they
were never actually tested before (not wrongly rejected), and now that they have been,
the result is negative on the correct window. No OOS Gate 0-4 needed (nothing passed
Gate 2 to escalate).

### Next steps (optional, not yet done)
- [ ] overnight.py (close 15:55 -> next-open 09:31) not yet run — different mechanism,
      not a "wrong window" re-test, can run if still of interest
- [ ] xsect/ (cross-sectional momentum) and nonequity/ (GC/CL) not covered by this
      session — separate NO-GO reasons (deferred / data availability), not window-related

### Files touched (read-only investigation, no production files modified)
None — orb_futures/, futures/, docs/futures/ all read-only this session.

---

## Sub-task: Opening Imbalance Filter for ORB (research) — 2026-08-03
Status: DONE — verdict MONITOR (no production change)

### Context
Hypothesis: does opening auction order imbalance predict direction/quality of the
existing ORB / STRESS_ORB_STK SHORT setup, independent of the already-validated
gates? Follows the catalyst-study method exactly (3-layer test), same event
population, same outcome metric — so results are directly comparable.
All code in `orb_stocks/imbalance_research/` — production untouched.

### Completed
- [x] **Step 1 coverage — GO.** Pre-committed thresholds set before first fetch.
      155/155 events usable on the `full` window (100%), 151/155 on `late` (97.4%),
      82 dates, both years clear. Tick-rule classification quality high
      (unclassified volume 0.0% median / 1.0% p90).
- [x] **Entitlement finding — hypothesis had to change.** Official NYSE/Nasdaq
      auction imbalance: ABSENT (404). Polygon NBBO quotes: **403 NOT_AUTHORIZED**
      → canonical Lee-Ready NOT constructible (needs quote midpoint). Only the
      TICK RULE remains. Measured object = pre-open signed order flow, NOT the
      auction imbalance. The original hypothesis remains untested.
- [x] **Step 2 features + confound — CLEAN.** Test variable chosen from the data
      (direction, not magnitude: magnitude fails the skew screen on `full`).
      `imb_ratio_vol` vs `gap_pct` spearman **+0.028**; vs pre-market volume rank
      **-0.016**. Raw sign-agreement 74% is pure base rate (98% down-gap × 75%
      sell-side → 74% chance); **Cohen's κ = +0.013**. Requirement #2 satisfied —
      this is NOT H1-H3 restated.
- [x] **Step 3 three-layer test.** Primary cell pre-committed (`late` × pct_return).
      naive p=0.157 → cluster p=0.100 → **within-date p=0.0267**, direction
      consistent. aligned n=110 +0.253% (WR56%) vs against n=34 -0.094% (WR47%).
      ICC=0.368, design effect 1.329, effective n=108.3.
      NOTE: opposite pattern to the catalyst study (there naive was strong and
      within-date killed it). Legitimate — high ICC means conditioning on date
      removes between-day noise — but see the sample-size caveat below.
- [x] **METHOD BUG FOUND + FIXED: `cluster_bootstrap.py` permutation is not centred.**
      It tests `|perm| >= |obs|` against zero, but non-mixed-date events contribute
      a fixed offset, so the null is centred at +0.123%, not 0.
      Uncentred p=0.0129 vs centred p=0.0267 — **overstated ~2x**.
      Fixed in `bootstrap_imbalance.py::layer3` (reports both).
      Catalyst verdict NOT overturned (p=0.524, far from threshold), but the bug
      is still live in `orb_stocks/cluster_bootstrap.py` for any future reuse.
- [x] **Step 3b robustness — this is what downgraded the verdict.**
      Leave-one-ticker-out: **QCOM (5 ev) → p=0.102**, **NVDA (10 ev) → p=0.065**
      (14 other tickers hold). Leave-one-date-out: 1/23 breaks it.
      Winsorise ±2sd: p 0.027→0.033 (PASSES — not tail-driven).
      Year split: **2022 p=0.020 (n=116) vs 2021 p=0.528 (n=28, 4 mixed dates)**.
- [x] **FINDINGS.md written** — full report, coverage, effective n, 3-layer results,
      robustness, revisit conditions.

### Verdict: MONITOR
Fails the pre-committed concentration rule (2 tickers break p<0.05) and the effect
is 2022-only. Not dead: direction consistent across all 3 layers, survives
winsorising, confound-clean, mechanism sensible (shorting into confirmed pre-open
selling). 2021 is *unconfirmed*, not contradictory — 4 mixed dates has no power.

### Key finding — why 5 events swing the p-value
The deciding test does NOT run on 144 events. Only **mixed dates** (both arms
present) have label freedom: **23 dates / 63 events (35 aligned, 28 against)**.
QCOM contributes 2 of the 28 against-events at -0.593%. The design-effect
"effective n=108.3" describes the full population, NOT the conditional test.
**Binding constraint for any revisit is mixed-date count, not event count.**

### Against promoting further
`full`-window cells point the OPPOSITE direction (-0.10%). Defensible (4am-8am
tape is noise) but not confirmation. With 4 cells examined, a Bonferroni read of
the primary gives 0.0267×4 ≈ 0.107 — no correction formally required since the
primary was pre-committed, stated so the number is not oversold.

### Revisit conditions
- [ ] More mixed dates (the binding power constraint, currently 23)
- [ ] 2023+ / OOS Stress data — is the 2022-only pattern regime- or sample-specific?
- [ ] NBBO quotes (plan upgrade) → real quote-based Lee-Ready; tick rule is strictly
      weaker, so current estimate is more likely a floor than a ceiling
- [ ] Official auction imbalance data — the hypothesis as written is still untested
- [ ] True all-days within-ticker baseline (~650 fetch-days) to enable z-score variants

### Files added (all research-only, production untouched)
orb_stocks/imbalance_research/: check_imbalance_coverage.py, build_imbalance_features.py,
bootstrap_imbalance.py, robustness_imbalance.py, FINDINGS.md,
imbalance_coverage.parquet, imbalance_features.parquet, imbalance_test_results.parquet

### POWER FIX — extended event index (2026-08-03, zero data cost)
- [x] **Root cause of the small sample found: an inherited window, not a data limit.**
      The 2021-04 start came from the catalyst study, where Polygon NEWS history
      begins ~2021-04. **The imbalance study uses no news** — that constraint never
      applied. Measured, not assumed:
        stress_orb_stk_sim.t_v3 : 237 trades / 121 dates, 2018-02-02 .. 2022-12-27
        window_debug_5min.pkl   : 75 tickers, 2017-01-03 .. 2024-12-31, NO gap
        Stress days             : 283 (2018:38 2019:25 2020:60 2021:47 2022:113)
- [x] `build_extended_event_index.py` — rebuilds over 2018-05-01..2022-12-31 using
      the committed sim unmodified (imported, not re-implemented) and the SAME
      outcome definition + |pct|>25% corrupt-bar gate as the catalyst study.
      Start = Databento imbalance history floor; 6 events / 2 dates before it
      dropped and reported.

      | metric | old | extended |
      |---|---|---|
      | clean events | 154 | **267** (x1.73) |
      | dates | 81 | **150** |
      | dates with >=2 events (mixed-date CEILING) | 45 | **72** (x1.60) |
      | years | 2 | **5** (2018-2022) |
      | tickers | 31 | 35 |

      Expected mixed dates ~36 (51% split rate observed) vs 23 now.
      Also directly attacks the "2022-only" robustness failure: adds 2018 (20 ev),
      2019 (24 ev), 2020 (56 ev).

### Databento — verified available, costed
- [x] `imbalance` IS a Databento schema (verified from installed SDK 0.80.0).
      `ImbalanceMsg` carries side, total_imbalance_qty, paired_qty, unpaired_qty,
      ref_price, ind_match_price, cont_book_clr_price, auction_type/time/status.
      This is the real NYSE/Nasdaq NOII — the input Polygon 404'd on.
- [x] `check_databento_imbalance.py` — metadata-only probe (no data downloaded).
      XNAS.ITCH   imbalance YES, history 2018-05-01..2026-08-03
      XNYS.PILLAR imbalance YES, history 2018-05-01..2026-08-03
      ARCX.PILLAR imbalance YES but NOT a listing venue for our pool -> skip ($48)
      BATS.PITCH / EDGX.PITCH: no imbalance schema
- [x] **Cost measured (date-sliced, linear, no per-request minimum):**
      extended 150 event dates x 35 tickers = **$6.07** (XNAS $4.11 + XNYS $1.96)
      vs full-window 2021-04..2022-12 = $16.70. Budget $37 -> ~$30.93 left.

### PENDING — user decision (spends real credit)
- [ ] Approve Databento fetch scope, then fetch + rebuild features + re-run
      bootstrap_imbalance.py / robustness_imbalance.py on the extended index

---

## Sub-task: STP không tồn tại ở IBKR dù runner báo đã đặt (2026-08-05)
Status: F0–F6 + nắn tick DONE (đã gate đầy đủ, 6 commit) — vị thế sống đã sửa xong và
xác minh — **bracket order CHƯA LÀM** là việc còn lại duy nhất của sub-task này

### Triệu chứng
Dashboard chỉ hiện 2 STP, đều là lệnh cũ. `live_positions.json` có 3 vị thế với
`stop_order_id` 62/66/70; IBKR không có lệnh nào trong số đó.

### Điều tra (client 88 read-only, `check_open_orders.py` + `check_completed_orders.py`)
- `/api/all` + CORS + dashboard: **không lỗi**. Panel hiển thị trung thực.
- 62/66/70 **không có trong open orders, cũng không có trong completed orders**
  → chưa từng vào sổ lệnh IBKR.
- 9/10 (clientId 93) vẫn PreSubmitted GTC — stop mồ côi từ phiên cũ. Order 10 là
  `SELL MYM` trong khi vị thế MYM đang SHORT → nếu fire sẽ **nhân đôi short**, không phải đóng.
- Log 12:40:25-28 ghi `place_stop: placed ... orderId=62/66/70`; 12:40:30 disconnect.

### ROOT CAUSE — ba lỗi cùng một lớp: gọi broker rồi không kiểm kết quả
1. **`place_stop` không xác minh gì.** Vòng `for _n in range(10): if trade.order.orderId != 0`
   (commit 42e1fc6, 12/07) kiểm một giá trị do ib_insync tự gán tại `ib.py:654/671`
   TRƯỚC khi hàm return → **điều kiện không thể sai**, nhánh `else` là code chết.
   Comment "ib_insync may not have the orderId synchronously" sai với 0.9.86.
2. **`cancel_order` dùng `ib.trades()`** — chỉ thấy lệnh phiên hiện tại, mà runner nối lại
   mới mỗi slot 5 phút → lệnh phiên trước luôn "not found". `has_working_stop` cùng file đã
   fix bằng `reqAllOpenOrders()`; `cancel_order` thì chưa.
3. **Call site vứt giá trị trả về** — `cancel_order` trả False chứ không raise, nên
   `try/except` không bắt được và log "cancelled" vô điều kiện.

### Vì sao các lần sửa trước không chặn được
- 42e1fc6 (12/07) nhắm triệu chứng khác (orderId=0 gây B3 NOT_FOUND giả), không nhằm xác minh.
- Fix 03/08 (`_verified_status`) chỉ áp cho `send_order` + 2 chân rollover. Next steps của
  chính phiên đó đã ghi "Rà các đường khác cũng đọc orderStatus.status — cùng lớp lỗi, chưa vá".
- **Tiêu chí nghiệm thu không thể đỏ**: "stop_order_id ≠ null" luôn đúng vì `place_stop`
  trả ID vô điều kiện. Xem mục ⏳ CHỜ VERIFY LIVE ở trên — đã thay tiêu chí.
- B4 (lưới an toàn) không nổ vì điều kiện là `stop_order_id is None`; **ID giả vô hiệu hóa nó**.

### Completed
- [x] **F3**: `_report_stop_cancel()` + sửa 2 call site (`run_day` CLOSE, `run_maxhold_exit`).
      Hủy thất bại → `logger.critical` + event CRITICAL/ORDER nêu đích danh orderId.
- [x] **F0**: thay tiêu chí nghiệm thu STP — phải hỏi IBKR (`check_open_orders.py`), không hỏi file.
- [x] TDD: `test_stp.py::test_stp9_orphan_alert_when_cancel_fails` +
      `test_maxhold.py::test_mh7_orphan_alert_when_cancel_returns_false`. Đỏ trước, xanh sau.
      (MH4 đã có nhưng chỉ phủ trường hợp `cancel_order` **raise**, không phủ trả `False`.)
- [x] GATE: reconcile_gd0 PASS 4/4 MATCH · reconcile_stress PASS 0 mismatch ·
      test_stp+test_maxhold 22/22 · test_ibkr_injection 14/14 · pytest suite 73 passed.

- [x] **F1** `place_stop` → `_await_stop_accepted(ib, trade)`: chờ status ∈
      (PreSubmitted, Submitted), timeout 5s (25×0.2s). PendingSubmit KHÔNG tính là nhận
      (đó là status ib_insync tự đặt ở `ib.py:673`). Thất bại → log status +
      `trade.log[-1].message` + return `''` → nhánh ALERT của runner sống lại, và
      `stop_order_id` giữ `None` nên B4 thấy được. Log đổi "placed" → **"accepted"**, kèm status.
- [x] **F2** `cancel_order`: `reqAllOpenOrders()` + `sleep(1.0)` rồi quét `openTrades()`
      thay vì `ib.trades()`.
- [x] **F4** `Broker.get_working_stops() -> dict | None` (non-abstract, khuôn `has_working_stop`).
      IBKRBroker: một round-trip `reqAllOpenOrders` cho mọi inst. MockBroker: **None**
      (không phải `{}` — nó không có sổ lệnh nên không thể làm chứng; trả `{}` sẽ khiến B4
      gọi mọi vị thế là naked và đổi hành vi verify mode). Điều kiện B4 nay là
      `stop_order_id is None OR (working is not None AND inst not in working)`.
- [x] **F5** `_audit_working_stops()` gọi cuối `run_day`, sau `_persist_state`, trước
      `dump_state`. Vị thế mở mà broker không có stop → CRITICAL + event CRITICAL/ORDER.
      Im lặng khi broker trả None. Không raise (chạy sau khi lệnh đã khớp).
- [x] **F6** rà xong: **`get_order_status` có cùng khe hở** — quét `trades()`→`fills()`→
      `openTrades()` mà không `reqAllOpenOrders()` trước. B3 dùng hàm này; NOT_FOUND sai
      → CRITICAL + halt entries. Đã vá. `find_execution` (dùng `reqExecutions` server-side)
      và 2 chân `_handle_rollover` (đã dùng `_verified_status` từ 03/08) — sạch.

### Test thêm (đỏ trước, xanh sau)
- `test_stp_accept.py` MỚI — 11 test: SA1–SA6 (`_await_stop_accepted`),
  CA1–CA3 (`cancel_order` cross-session), GS1–GS2 (`get_order_status` cross-session)
- `test_stp.py` — B4.6/B4.7 (ID giả vs broker làm chứng), STP10/11/12 (quét cuối phiên)

### GATE sau F1–F6 (chạy lại đầy đủ)
reconcile_gd0 **PASS** 4/4 MATCH · reconcile_stress **PASS** 0 mismatch ·
pytest 8 suite **80 passed** · test_ibkr_injection **14/14** ·
lỗi có sẵn không đổi: test_operational_fixes 7 FAIL, test_event_playback 9 FAIL,
test_rollover 1 FAIL — giống hệt HEAD.

### ROOT CAUSE THẬT tìm được khi chạy repair trên tài khoản sống (2026-08-06)
**IBKR code 110 — giá không đúng bước giá.** Mức chandelier là số liên tục, không mức nào
nằm trên lưới tick: 7758.86 (MES tick 0.25) · 54708.68 (MYM tick 1.0) · 3038.44 (M2K tick 0.1).
IBKR từ chối cả ba hôm 05/08; `place_stop` đọc lại orderId của chính mình nên ghi "placed".
Đây là câu trả lời cho câu hỏi mà 3 commit trước chưa trả lời được: stop **chưa bao giờ được nhận**.
F1 đã tự chứng minh giá trị — nó báo cú từ chối thay vì giấu.

- [x] `_round_stop_to_tick(inst, direction, price)` — nắn về lưới tick, **hướng ra xa thị trường**
      (LONG làm tròn xuống, SHORT làm tròn lên). Tròn về phía thị trường sẽ thắt stop chặt hơn
      mức đã sizing, và ở gần giá có thể đẩy xuyên qua → nổ ngay. Inst lạ → giữ nguyên.
- [x] Log `place_stop` in **giá đã gửi**, không phải giá yêu cầu.

### Ba lỗi cùng họ, phát hiện khi DÙNG công cụ trên tài khoản sống (không phải khi đọc code)
- [x] `get_working_stops` + `has_working_stop` dùng danh sách **loại trừ** → lệnh kẹt ở
      `PendingSubmit` (hình dạng của lệnh bị từ chối) được tính là đang bảo vệ. B4 và F5 đều
      đọc hai hàm này. Nay yêu cầu `PreSubmitted`/`Submitted`.
- [x] `cancel_order` trả `True` ngay sau `cancelOrder` mà không kiểm lệnh đã rời sổ.
      MYM #10 bị "hủy" 2 lần, báo thành công 2 lần, vẫn sống. Nay poll trạng thái terminal,
      thất bại → `False` + hướng dẫn dùng TWS. **Kết luận: hủy chéo client bị từ chối.**
- [x] `classify` gọi OK cho vị thế vừa có stop đúng chiều vừa có stop sai chiều → công cụ in
      "every position protected" trong khi một stop nhân đôi vị thế đang sống. Nay báo `HAZARD`.

### Công cụ
- [x] `check_open_orders.py` — chẩn đoán, read-only, exit 1 nếu có khe hở. Verdict:
      OK / HAZARD / WRONG-WAY / NAKED / ORPHAN.
- [x] `repair_stops.py` — sửa; dry-run mặc định, `--execute` mới gửi. Đi qua
      `IBKRBroker.place_stop`/`cancel_order` nên mỗi lần sửa cũng là một lần nghiệm thu F1.
      Hai từ chối không ghi đè được: stop sai phía thị trường, và stop trùng trên cùng contract.

### Trạng thái sống sau khi sửa (2026-08-06 ~01:30 local)
MES SELL #9 @7627.25 · MYM BUY #12 @54709.00 · M2K BUY #14 @3038.50 — cả ba đúng chiều.
- [x] **MYM SELL #10 @53290 ĐÃ HỦY.** Không cần TWS, không cần restart: IBKR chỉ nhận lệnh
      hủy từ **chính clientId đã đặt**. Thử từ 1/77/82 đều bị từ chối im lặng; nối lại bằng
      `--client-id 93` (id đã đặt nó) thì hủy được ngay lần đầu.
      `cancel_order` nay in `clientId` chủ trong thông báo lỗi để lần sau biết đường chạy.
- [ ] **Scheduler đang TẮT** (đã dừng PID 4960 để chạy repair). Bật lại:
      `python -m global_index.run_scheduler --port 4002`
- MES giữ stop 7627.25 thay vì 7758.86 (rộng hơn 131 điểm) — quyết định giữ nguyên,
      vì thay nghĩa là có một khoảng không stop, và 7758.86 chỉ cách giá ~3 điểm.

### ✅ VERIFY LIVE ĐÃ QUA — phiên 2026-08-06 (tiêu chí F0 mới, hỏi IBKR chứ không hỏi file)
Entry M2K SHORT lúc 12:30 local, đi trọn đường code đã vá:
```
12:30:16  place_stop: M2K SHORT stop 3020.0900 → 3020.1000 (tick 0.1)
12:30:17  place_stop: accepted SHORT M2K STP ×1 @ 3020.1000 orderId=100 status=PreSubmitted
```
Nắn tick làm tròn **lên** cho SHORT (ra xa thị trường) + xác nhận trạng thái thật.
Code cũ sẽ gửi 3020.09 → IBKR từ chối code 110 → ghi "placed" với id bịa.
`check_open_orders.py` → **PASS**, 2/2 vị thế có stop đúng chiều.

**Stop đầu tiên nổ thật (M2K, 08:11 local = 10:11 ET):** `reqExecutions` xác nhận
`BOT 1 M2KU6 @ 3038.60` ordId=14 — stop đặt 3038.50, **trượt đúng 1 tick** (giả định
backtest 2 tick/chiều). Vị thế đóng đúng, lỗ ≈ $28.6.

### Hai lỗi nữa lộ ra khi theo dõi cú khớp đó (đã vá, xem commit)
- **`ib.openTrades()` là cache tích lũy, không phải sự thật ở broker.** Backend dashboard
  vẫn báo stop đã khớp là `PreSubmitted` **16 phút sau**. Chỉ tiến trình sống lâu mới dính →
  vô hình với test và script ngắn. Đã đổi 5 chỗ sang dùng giá trị `reqAllOpenOrders()` trả về.
  `verify_account_clean` còn gọi `openTrades()` mà không `reqAllOpenOrders()` → **false clean**.
- **`repair_stops` không sửa `stop_order_id` khi SKIP.** Đây là thứ đã nuôi con ma: MES giữ
  id bịa 62 bên cạnh stop thật #9. Lúc đóng MES hôm 06/08, runner hủy 62 → thất bại →
  F3 báo CRITICAL đúng lúc **nhưng nêu sai lệnh**, và #9 nằm lại mồ côi (SELL STP không có
  vị thế → sẽ MỞ short nếu nổ). Đã thêm `id_corrections()`; #9 hủy xong bằng `--client-id 93`.

### Next steps
- [ ] **Bracket order** (khảo sát xong, chưa làm) — xem Key decisions.

### Key decisions
- **Bracket khả thi**: `stop_price` là mức cố định lúc entry, **không ratchet**
  (runner.py:1099 + :1307 ghi rõ "not ratcheted yet") → không cần modify STP hằng ngày,
  tức trở ngại lớn nhất của bracket không tồn tại. Dựng tay bằng
  `MarketOrder(transmit=False)` + `StopOrder(parentId, transmit=True, tif=GTC, outsideRth=True)`;
  KHÔNG dùng `ib.bracketOrder()` vì nó ép parent LMT và bắt buộc chân take-profit (ib.py:572-613).
- **Bracket KHÔNG thay thế F1/F2/F4/F5.** Nó xoá khoảng hở giữa fill và lúc đặt STP, nhưng
  vẫn cần: xác minh bracket được nhận (F1), hủy STP khi thoát bằng lệnh riêng (F2/F3),
  và lưới phát hiện vị thế trần (F4/F5). Vì vậy F1/F2/F4/F5 làm trước, bracket là bước sau.
- Chưa xác minh được (cần phiên live): IBKR có nhận parent MKT trong bracket không; child STP
  còn sống hay tự hủy khi ta đóng vị thế bằng lệnh MKT riêng.

### Việc tay — ĐÃ XỬ LÝ XONG bằng repair_stops.py (2026-08-06 ~01:30 local)
- [x] Hủy order 10 (`SELL MYM STP @53290`) — **không cần TWS**: nối bằng `--client-id 93`
      (id đã đặt nó). Thử từ 1/77/82 đều bị từ chối im lặng.
- [x] MYM có BUY STP #12 @54709.00 · M2K có BUY STP #14 @3038.50 — đặt được sau khi vá tick.
- [x] `stop_order_id` trong `live_positions.json` cập nhật theo (backup `.json.bak`).
- [x] Order 9 (`SELL MES @7627.25`): **quyết định giữ nguyên**. Đúng chiều, có bảo vệ.
      Thay nó nghĩa là có một khoảng không stop, và mức đúng 7758.86 chỉ cách giá ~3 điểm
      nên nhiều khả năng bị quét ngay. Rủi ro rộng hơn dự tính 131 điểm — đã biết, có giới hạn.

### Lỗi có sẵn phát hiện lúc chạy gate (KHÔNG do phiên này, đã kiểm bằng stash)
- `test_rollover.py::test_ro6_maxhold_then_rollover_no_conflict` đỏ y hệt trên HEAD.
- `test_operational_fixes.py` 7 FAIL, `test_event_playback.py` 9 FAIL — số lượng giống hệt
  trước và sau thay đổi.

### Files touched
`global_index/`: runner.py · ibkr_broker.py · broker.py · check_open_orders.py (mới) ·
repair_stops.py (mới) · test_stp_accept.py (mới) · test_stp.py · test_maxhold.py
Gốc: TASK.md · SCRATCHPAD.md

### Commits
```
dabd75c fix(stp): correct a recorded stop id even when the position needs no repair
75a5aef fix(ibkr): read open orders from reqAllOpenOrders, not the ib_insync cache
03df38c fix(stp): a failed cancel names the clientId that can actually do it
6a39c58 fix(stp): round stop prices to the tick grid — the actual cause of the naked positions
eb5309f feat(stp): repair tool, and fix instrument-name lookup for NKD stops
80d2bae test(stp): replace an acceptance criterion that could never fail
c40b136 fix(stp): detect naked positions from broker truth, not from a local field
fdfad29 fix(stp): place_stop confirms IBKR accepted the order instead of its own id
```

---

## Sub-task: STRESS_MID — lệnh đóng same-day thất bại thì không ai thấy (2026-08-08)
Status: PHÁT HIỆN, **CHƯA SỬA** — có sẵn từ trước, không do phiên này gây ra

STRESS_MID mở và đóng trong cùng một `decide_day`, nên nó **không bao giờ thành `OpenPos`**
và **không được đặt stop** (STP3 khẳng định: `place_stop` không gọi cho lệnh same-day).
Khối same-day trong `run_day` gửi OPEN rồi CLOSE **không kiểm status**:

- CLOSE thất bại → `avg_price = 0` → không ghi sổ (đúng, guard mới chặn)
- Nhưng vị thế **đang mở thật ở broker**, mà runner không theo dõi gì cả
- `_audit_working_stops` (F5) duyệt `state.open_positions` → **không thấy nó**
- Không có `exit_pending`, không có retry — khác hẳn đường multi-day vốn có I4.8

→ **Vị thế qua đêm, không stop, vô hình với mọi guard trừ B3 ở slot kế tiếp** (bắt được
dưới dạng ORPHAN → CRITICAL + halt, tức phát hiện muộn và phản ứng là dừng chứ không
phải bảo vệ).

Cần quyết:
- [ ] Same-day CLOSE thất bại thì nên: giữ thành `OpenPos` có `exit_pending=True` để
      retry như đường multi-day, và đặt stop bảo vệ? Hay đóng lại ngay bằng lệnh khác?
- [ ] F5 có nên quét cả vị thế broker báo mà file không có, thay vì chỉ `state.open_positions`?

---

## Sub-task: Sổ cái sleeve đo sai — bám net-liq tài khoản thay vì P&L giao dịch
Status: **DONE** (97e0f7c) — đã rebase về epoch mới $50,000 ngày 2026-08-07

### Kết quả
- [x] Bỏ H4 khỏi đường sổ cái. `equity = ACCOUNT + Σ realized P&L của lệnh sleeve`,
      **realized-only** đúng quy ước `deploy_sim.replay:77`.
- [x] `OpenPos.entry_price` + lưu xuống file. Live `pnl_sized` về 0.0 nên không có giá vào
      thì không định giá được lệnh đóng.
- [x] **Bốn** đường đóng đều ghi sổ: signal exit · max hold · retry · stop nổ ở broker.
      `run_maxhold_exit` **chưa bao giờ** cộng P&L vào sổ cái.
- [x] Vị thế không có `entry_price` → CRITICAL + bỏ qua, không ghi bừa số 0.

### Phát hiện: verify mode cũng sai, và không gate nào bắt được
`decide_day` cộng `pnl_sized`, rồi H4 cộng tiếp delta broker cho **cùng một lệnh** →
`state.equity = ACCOUNT + 2 × realized`. Sống sót vì `verify_runner_real.py` chỉ so
`broker.get_equity()` (con số MockBroker giữ, vốn đúng), **không bao giờ so
`runner.state.equity`** — tức con số circuit breaker đọc.
- [x] Gate nay kiểm cả hai. Chạy 3072 lệnh thật: `Sleeve ledger $109,820.69 =
      expected $109,820.69 PASS`.
**L18: gate kiểm con số dễ lấy, không kiểm con số được dùng để ra quyết định — thì nó
không kiểm gì cả.**

### Verify mode nguyên vẹn — ba lớp độc lập
1. `MockBroker` không set `avg_price` (chỉ IBKRBroker set) → nhánh định giá live không chạy
2. `signal_layer` không set `pnl_sized` → live `decide_day` cộng 0 → không đếm hai lần
3. H4 trong verify vốn là no-op → xoá không đổi gì
GATE: reconcile_gd0 4/4 MATCH · reconcile_stress 0 mismatch · verify_runner_real ALL PASS
· pytest 134 · injection 14/14.

### Rebase — QUYẾT ĐỊNH: epoch mới từ $50,000 (2026-08-07)
Lý do: mọi lệnh 08-03→08-07 do code có lỗi đã biết sinh ra (stop chưa từng tới IBKR,
stop nổ ngay khi đặt, exit không ai ghi, sổ cái đếm nhầm). Đo degradation-vs-backtest
trên mẫu đó là **đo lỗi, không đo chiến lược**. Cùng mốc $50k với backtest nên Calmar/DD
so trực tiếp được.
- [x] `system_equity` / `peak_equity` / `day_start_equity` = 50,000.00
- [x] `system_epoch` = null → runner tự đóng dấu ngày chạy thật đầu tiên
- [x] `last_broker_equity`, `cur_day` gỡ bỏ → tự khởi tạo lại
- [x] `entry_price` MYM SHORT = **54631.00** (từ statement) — không có thì lệnh đóng ra CRITICAL
- [x] **Gỡ vị thế MES SHORT ma** — stop #196 đã khớp ở broker 08-07 14:01 local, runner
      chưa kịp đối chiếu. Để lại thì B3 thứ Hai thấy IBKR trống vs file có, hỏi
      `reqExecutions` (khi đó đã quên fill thứ Sáu) → **HALT entries**.
- [x] Xác minh sau rebase: `check_open_orders.py` → PASS, 1 vị thế, stop đúng chiều.
- Backup: `live_positions.json.prerebase.bak`
- **KHÔNG reset tài khoản paper**: thứ mà reset để sửa (nhiễm bẩn CAD/lãi/FX) đã sửa bằng
  code; reset sẽ phá nguồn đối chiếu độc lập (statement) vừa dựng được, mà không sửa thêm gì.

### ⚠️ HỆ QUẢ AN TOÀN CHƯA GIẢI QUYẾT — bỏ H4 đã gỡ mất phanh trong ngày
`test_operational_fixes` T29.1/T29.2/T31.3/T31.4 **đỏ sau 97e0f7c**, và chúng nói đúng.

T29 mô phỏng: IBKR báo equity đã mất 4.2% trong ngày vì các fill mà sổ cái runner
**chưa kịp ghi**. H4 cũ đồng bộ khoản đó vào `state.equity` → `daily_loss ≥ 4%` →
**HALT_DAY** → chặn mọi lệnh vào mới. Bỏ H4 thì cơ chế đó biến mất:
**lỗ chưa thực hiện trong ngày không còn kích hoạt HALT_DAY nữa** — phanh chỉ nổ khi
có lệnh ĐÓNG.

Hai điều cùng đúng, và đó là chỗ khó:
- H4 cũ đo **cả tài khoản** (CAD ~$997k) → HALT_DAY có thể nổ vì FX hoặc lãi tiền gửi.
  Đó không phải bảo vệ, đó là nhiễu. Bỏ là đúng.
- Nhưng nó ĐỒNG THỜI là phanh duy nhất đọc sự thật từ broker trong ngày. Gỡ đi là mất thật.
- Quy ước realized-only khớp `deploy_sim.replay` — backtest cũng chỉ HALT_DAY trên realized.
  Nên live nay **khớp backtest hơn trước**, đổi lại là ít bảo vệ hơn trước.

### ✅ ĐÃ CHỌN: (b) realized-only ở mọi chỗ — lý do, và cái phải nhớ

**Vì sao phanh nhận-biết-unrealized không thêm được gì:** breaker **chỉ gác cửa vào lệnh**
(`allow_new_entries`), nó không đóng vị thế. Xét mọi tình huống lỗ chưa thực hiện lớn:
- **Thị trường đang giao dịch** → stop kích hoạt và khớp trong vài giây (kể cả ở giá tệ
  hơn nhiều). Lỗ thành realized → vào sổ trong ≤5 phút → **phanh hiện tại bắt được**.
- **Thị trường ngừng** (limit-down, halt, cuối tuần, nghỉ 17:00–18:00 ET) → stop không
  khớp được và lỗ phình lên, nhưng **cũng không vào lệnh mới được** → phanh không có việc.

⚠️ **Cái phải nhớ — `risk_dollars` là ƯỚC LƯỢNG lỗ, KHÔNG phải trần lỗ.**
Stop là lệnh *kích hoạt*, không phải lệnh giới hạn: SHORT 7778 / stop 7790, giá nhảy lên
7900 → khớp ở **7900**, lỗ `$610` thay vì `$60` — **gấp 10× `risk_dollars`**. Nên "cap
cluster 9.5%" là trần của rủi ro *dự tính*, không phải của lỗ *thực tế*. Vài cú gap liên
tiếp đi xuống qua 15% — và cái đó phanh hiện tại BẮT ĐƯỢC vì đã realized.
→ Muốn bảo vệ thật cho phần này thì hướng đúng là **đo slippage thoát thực tế so với mức
stop** (C1 đã ghi sẵn trường `slip` trong trade_log), không phải thêm một phanh gác cùng
một cái cửa.

⚠️ **Toàn bộ lập luận đứng trên giả định: stop TỒN TẠI và đặt ĐÚNG PHÍA.**
Ba ngày 08-05→08-07 giả định đó sai. Khi stop hụt thì cap vẫn cho vào lệnh mà lỗ không
còn trần. Nghĩa là F1 (xác minh IBKR nhận thật) · F5 (quét cuối phiên) · B4 (đối chiếu
đầu slot) **không phải chuyện sổ sách — chúng là lớp kiểm soát rủi ro chính**. Một stop
đặt hụt không phải lỗi ghi log, nó là mất trần lỗ. Không được nới các guard này.

### Đã làm (eba58ca)
- [x] `test_equity_base.py` eq4/eq5/eq6 viết lại theo quy ước mới, 9/9 xanh.
      eq4 **đảo chiều** (sổ cái phải BỎ QUA biến động broker); eq5 trước đó **pass vô
      nghĩa** (không còn gì làm equity dịch chuyển nên "không ghi hai lần" đúng tự động);
      eq6 giữ nguyên tính chất, khoản lỗ nay đến từ lệnh đóng thật.

### ⚠️ PHÁT HIỆN MỚI — phanh ngày mù với lệnh đóng ĐẦU TIÊN trong ngày
Lộ ra khi viết lại T29 (commit 19070df). `decide_day` ghi exits **rồi mới** đặt mốc ngày:
```python
for p in state.open_positions:            # 1. ghi exits  → equity 47,500
    if p.exit_day == day: state.equity += p.pnl_sized
if day != state.cur_day:                  # 2. RỒI mới đặt mốc
    state.breaker.start_day(state.equity)     # ← mốc = 47,500, không phải 50,000
```
→ **Lỗ hiện thực hoá ở sự kiện đầu tiên của một ngày tự đặt mốc ngày xuống dưới chính
nó**, `daily_loss = 0`, HALT_DAY không nổ. Phanh ngày chỉ thấy khoản lỗ realized **sau**
lệnh đóng đầu tiên trong ngày.

`decide_day` sao chép đúng thứ tự `deploy_sim.replay` → **backtest cũng vậy**. Không phải
do thay đổi sổ cái gây ra; nó vô hình suốt thời gian H4 cấp chuyển động từ bên ngoài.

Câu hỏi cần trả lời (CHƯA):
- [ ] Có chủ ý không? Nếu mốc ngày phải là equity **cuối ngày hôm trước** thì `start_day`
      phải gọi TRƯỚC vòng exits — nhưng đổi thứ tự này **đụng `decide_day`, tức đụng
      đường khớp trade-for-trade với `deploy_sim`**. Phải gate bằng reconcile.
- [ ] Nếu là chủ ý: HALT_DAY thực chất chỉ gác các lệnh đóng thứ 2 trở đi trong ngày —
      nên ghi rõ vào tài liệu rủi ro, đừng để ai tưởng nó gác cả ngày.

### Còn lại của (b)
- [ ] `test_operational_fixes.py` **T29.1/T29.2/T31.3/T31.4** — chưa viết lại. Chúng kiểm
      một tính chất khác eq6: entry đã được `decide_day` **duyệt** rồi bị chặn **lại** ở
      cuối `run_day` sau khi equity đổi. Khối kiểm tra đó **vẫn còn** (runner.py:1436) và
      nay đọc `state.equity` do `_book_realised` làm dịch chuyển.
      Cách viết lại: signal vừa ĐÓNG một lệnh lỗ ≥4% vừa MỞ lệnh mới trong cùng ngày →
      close ghi lỗ → khối cuối `run_day` phải chặn entry đó.
- [ ] ⚠️ **Khối chặn đang gác bằng sai điều kiện**: nó nằm trong `if abs(_h4_delta) > 0.01:`
      — tức gác bằng **delta broker** trong khi thứ nó đọc là **sổ cái**. Thực tế vẫn chạy
      (mọi fill đều làm net-liq dịch chuyển), nhưng điều kiện nên đổi sang "sổ cái vừa đổi".

**Ba hướng đã cân nhắc (giữ để tham chiếu):**
- [ ] **(a) Khôi phục phanh, đo đúng sleeve.** Thêm method broker trả tổng
      `unrealizedPnL + realizedPnL` của **riêng vị thế ta** (IBKR có sẵn per-position,
      `/api/all` đang trả). Dùng cho **kiểm tra breaker trong ngày**, KHÔNG ghi vào sổ cái.
      Tách bạch: `state.equity` realized-only cho báo cáo/so backtest; phanh có thêm
      mark-to-market của sleeve. Đúng nhất, tốn công nhất.
- [ ] **(b) Chấp nhận realized-only ở mọi chỗ.** Khớp backtest tuyệt đối. Đổi lại: một vị
      thế lỗ nặng trong ngày không chặn được lệnh vào mới cho tới khi nó đóng.
      Cập nhật T29/T31 theo quy ước mới.
- [ ] **(c) Hoàn tác phần bỏ H4**, giữ lại phần còn lại của 97e0f7c. Quay về nhiễu FX/lãi.

⚠️ **KHÔNG sửa T29/T31 cho xanh trước khi chọn.** Chúng đang mã hoá một cơ chế bảo vệ
thật; viết lại để pass là xoá bằng chứng thay vì ra quyết định.

Hiện tại scheduler ĐANG TẮT nên không có rủi ro sống.

### Không tính vào đánh giá — giai đoạn chạy rà 2026-08-03 → 08-07
Giữ trong `trade_log` + statement làm hồ sơ, nhưng **loại khỏi mẫu đánh giá**:
realized +$1,136.25, trong đó có 5 vòng MES ngày 08-07 stop nổ sau 1–2 giây
(lỗi offset khi append parquet — user đang sửa riêng) và 3 vị thế 08-03 qua đêm trần trụi.

---

## Sub-task: Sổ cái sleeve — bối cảnh gốc (giữ để tham chiếu)

### Triệu chứng
Sổ cái báo `net_pnl = +$2,212.33`; giao dịch thật làm ra `+$1,136.25`. `sharpe = 12.07`.

### ROOT CAUSE (số học, kiểm được)
[runner.py:1353](global_index/runner.py#L1353) — H4: `self.state.equity += _h4_delta`, với
`_h4_delta = broker.get_equity() - _last_broker_equity`, tức **biến động NetLiquidation
của CẢ tài khoản**.
```
broker : 997,756.40 − 997,395.69 = +360.71
sổ cái :  52,212.33 −  51,851.62 = +360.71   ← giống hệt, 1:1
```
Tài khoản gốc **CAD**, quy mô ~$997k = **20× sleeve $50k**. Statement 7 ngày liệt kê thẳng
các khoản không phải giao dịch cùng chảy vào:
```
Credit Interest  +1,374.32 CAD   ← lãi tiền gửi 1 tháng, CÙNG CỠ toàn bộ P&L giao dịch
Debit Interest      −19.45
Adjustment           −6.56       ← FX Translations P&L
```
⚠️ Calmar / Sharpe / Max DD / degradation-vs-backtest **và ngưỡng circuit breaker** đều
tính trên đường cong này.

### Quy ước phải theo — không phải lựa chọn
`deploy_sim.replay:77` — `equity += t["pnl_sized"]` rồi `breaker.update(equity)`.
Backtest là **realized-only, không mark-to-market**. Toàn bộ baseline IS (floor 1.65)
sinh ra dưới quy ước đó. Sổ cái live phải trùng, nếu không thì:
(a) so paper vs backtest là so hai đại lượng khác nhau;
(b) phanh nổ theo điều kiện khác điều kiện nó được kiểm định.
→ **`equity = ACCOUNT + Σ realized P&L của lệnh sleeve`**. Unrealized hiện riêng trên
dashboard, KHÔNG vào mẫu số rủi ro.

### Thiết kế — 5 phần, PHẢI hạ cánh trọn gói
Làm nửa vời = closes cộng `pnl_sized` **và** H4 cộng broker delta → **đếm hai lần** đúng
con số phanh đang dùng.

- [ ] **1. `OpenPos.entry_price: float | None = None`** ([live_decision.py:37](global_index/live_decision.py#L37))
      + `_openpos_to_dict` / `_openpos_from_dict` mang theo (dùng `.get` → tương thích ngược
      với file cũ; vị thế cũ có `entry_price=None` và không tính được P&L → phải log CRITICAL,
      không được lặng lẽ tính bằng 0).
- [ ] **2. Ghi giá vào khi OPEN khớp** — `Fill.avg_price` đã có sẵn và IBKRBroker đã set.
- [ ] **3. Tính realized khi CLOSE**, `pnl = (exit − entry) × point_value × contracts ×
      (+1 LONG / −1 SHORT)`, gán vào `p.pnl_sized`. **Hai đường, cả hai đều phải làm**:
      lệnh đóng chủ động, và **stop nổ** (nhánh B3 STP-VERIFY — nay đã có giá nhờ dcd1b6e).
      Đường cộng equity đã sẵn sàng, không cần đổi: runner.py:788, live_decision.py:88 và :127.
- [ ] **4. Bỏ H4** ([runner.py:1345-1353](global_index/runner.py#L1345)). Verify mode không
      ảnh hưởng: MockBroker cho delta ≈ 0 nên đây là no-op ở đó → reconcile không đổi.
      Giữ lại `breaker.update()` + chặn entry sau khi equity đổi, chỉ đổi nguồn của delta.
- [ ] **5. Rebase (một lần, cần user duyệt)** — equity và `peak_equity` hiện xây trên số
      nhiễm bẩn. Thật: `50,000 + 1,136.25 = 51,136.25`; đang lưu `52,212.33`, peak `51,892.58`.
      Chuyển thẳng sẽ tạo drawdown giả ~1.46%. Dựng lại cả hai từ chuỗi realized đã đối chiếu
      (`reconcile_statement.py` cho đủ số).

### Test bắt buộc (đỏ trước)
- Broker trả `avg_price` ở OPEN/CLOSE **và** `get_equity()` nhảy một khoản tuỳ ý (giả lập lãi
  tiền gửi) → sau open+close, `equity == ACCOUNT + P&L giao dịch`, **không** dính khoản nhảy đó.
  Đây là test định nghĩa cả thay đổi.
- Stop-exit cũng phải cộng equity (không chỉ xoá vị thế khỏi state).
- Vị thế cũ `entry_price=None` → CRITICAL, không âm thầm coi P&L = 0.
- GATE: reconcile_gd0 + reconcile_stress phải **không đổi** (chứng minh verify mode nguyên vẹn).

### Vì sao chưa làm trong phiên 2026-08-07
Chạm đường tiền ở 4 chỗ / 2 module + đổi schema + cần migration. Bản vá nửa chừng đếm equity
hai lần, mà đó là mẫu số của circuit breaker, trên tài khoản đang chạy thật qua đêm.
Ghi lại để phiên sau thực thi trọn gói và gate đầy đủ.

---

## Sub-task: Slot NKD đêm không chạy — ROOT CAUSE xác định (2026-08-06)
Status: ROOT CAUSE XONG — nửa code DONE (ddae2f9) — **nửa môi trường (powercfg) CHƯA LÀM**
— **scheduler cần khởi động lại để nhận code mới**

### Triệu chứng
0/22 slot NKD đêm (01:10–02:55 ET) chạy đêm 05→06. **Không một dòng log nào** sau 16:00 ET
hôm trước, kể cả misfire. Tiến trình vẫn sống (PID 4960, 4 luồng Wait, CPU 2.4s/15h).
Job có đăng ký đủ vào đúng instance đang chạy (09:26:19), cờ pre-flight 05/08 = true,
thứ Năm là ngày làm việc. Suy giảm: 08-03 chạy 22 slot → 08-04 chạy 4 → 08-05 chạy 0.

### ROOT CAUSE
`threading.Event.wait(timeout)` trên Windows đếm bằng đồng hồ **không chạy khi máy ngủ**.
`BlockingScheduler` chờ **một lần dài** tới job kế (14:00:28 → 23:10:00 = ~9h10m), nên mỗi
giây máy ngủ đẩy lùi hạn chờ đúng một giây — **kể cả khi máy đã thức lại từ lâu**.

**Kiểm chứng định lượng (đêm 04→05, có số đối chứng độc lập):**
- Tổng ngủ trong khoảng chờ: **1:27:37** (Power-Troubleshooter)
- Dự đoán thức: 23:10:00 + 1:27:37 = **00:37:37**
- APScheduler thực tế xử lý job: **00:37:22** → lệch **15 giây**

**Áp cho đêm 05→06:** ngủ 19:10:56–22:02:23 (2h51m27s) + 23:20:50–00:03:11 (42m21s)
→ hạn 23:10 bị đẩy tới **02:43:48**, sau khi cửa sổ đêm đóng lúc 00:55.

⚠️ Giấc ngủ lúc **19:10 chiều** — thời điểm không có job nào — đã vô hiệu hóa **toàn bộ**
cửa sổ đêm 4 tiếng sau đó. Không cảnh báo nào vì không có gì hỏng; nó chỉ đang chờ.

### Giả thuyết đã bị bác bỏ dọc đường
- ~~Job không đăng ký~~ — có đủ 22 job lúc 09:26:19.
- ~~Cờ pre-flight chặn~~ — cờ 05/08 = true, và slot bị chặn sẽ LOG "SKIPPED" (đêm 04 có log đó).
- ~~Máy ngủ suốt cửa sổ~~ — máy thức ở 23:10, 23:15 và 00:05–00:55.
- ~~Đo bằng `Kernel-Power 42/107`~~ — nguồn này chỉ ghi 11 giây trong khi thực tế 3h33m.
  Nguồn đúng: **`Microsoft-Windows-Power-Troubleshooter`** (Sleep/Wake Time, UTC).

### Completed — nửa code (commit ddae2f9)
- [x] **Heartbeat mỗi phút, 7 ngày/tuần** (`id="heartbeat"`). Hai tác dụng:
      (1) chặn trần `wait_seconds` xuống 60s → sau khi máy thức, scheduler đánh giá lại
      trong vòng một phút thay vì hàng giờ;
      (2) tự đo mình bằng **đồng hồ tường** (đồng hồ này CÓ chạy khi máy ngủ) → khoảng
      cách giữa hai nhịp chính là thời gian đình trệ, log ra thành **con số** thay vì im lặng.
      Chạy cả cuối tuần: đình trệ bắt đầu tối thứ Sáu phải thấy được trước slot thứ Hai.
- [x] `heartbeat_gap(prev, now)` — hàm thuần, dung sai 30s cho cron drift. Kêu quá dễ thì
      cảnh báo bị bỏ qua, đúng cách mà lỗi này sống sót 3 đêm.
- [x] **`SLOT_MISFIRE_GRACE_SECS = 300`** cho **toàn bộ** 45 slot live-day + nkd-night.
      Mặc định APScheduler là **1 giây** → slot trễ dù chỉ chút xíu là bị bỏ âm thầm.
      300s vì: slot cách nhau 5 phút và `diff_desired_vs_held` idempotent → trễ vài phút
      vẫn làm đúng việc của slot bị lỡ; quá đó thì slot kế đã lo, mà bắn muộn sẽ đưa lệnh
      NKD vào cách bar tín hiệu hàng giờ.
- [x] `test_scheduler_heartbeat.py` — 8 test (đỏ trước): phát hiện đình trệ, dung sai,
      heartbeat có đăng ký, chạy cả 7 ngày, và **mọi slot dùng chung một chính sách grace**.
- [x] GATE: reconcile_gd0 PASS 4/4 · test_ibkr_injection 14/14 · pytest 113 passed.

### ✅ VERIFY LIVE ĐÊM 06→07 — CỬA SỔ NKD CHẠY ĐỦ
Scheduler đã restart, heartbeat hoạt động. Slot đêm nổ **14 lần liên tiếp đúng giờ**
(01:10 → 02:20 ET, mỗi slot cách nhau đúng 5 phút, tất cả `completed OK`).
**Tất cả `entries=0 exits=0 rejected=0`** — cửa sổ chạy đúng, chỉ là không có tín hiệu NKD.
Không phải "không chạy" như ba đêm trước; đây là "chạy và không có gì để làm".

### Lỗi tự gây ra và đã sửa ngay (commit 73af8cd)
Heartbeat khiến APScheduler log mỗi lần dispatch ở INFO → **2880 dòng/ngày**. Đo trên log
thật chỉ vài giờ sau khi bật: **153/693 dòng = 22%**, và dòng slot thật bị kẹp giữa chúng.
Một watchdog làm log không đọc được thì tự đánh bại chính nó — log không ai đọc chính là
điều kiện đã để lỗi gốc sống ba đêm.
- [x] `HeartbeatNoiseFilter` trên file handler: bỏ đúng dòng dispatch của heartbeat,
      giữ nguyên dispatch của slot thật (đó là bằng chứng slot đã nổ) và giữ cảnh báo STALLED.
- [x] Nhịp đổi sang **INFO mỗi giờ** (24 dòng/ngày) thay vì DEBUG mỗi phút. Đủ để
      "log im lặng" thôi là trạng thái mơ hồ — đúng thứ cả bản vá này sinh ra để xoá.
- [x] 3 test nữa (hb9–hb11): bỏ nhiễu, giữ dispatch slot, **không bao giờ** lọc STALLED.

### Next steps — CHƯA LÀM

**(b) Nửa môi trường — BẮT BUỘC, làm trước, rẻ nhất**
- [ ] Đặt máy không ngủ khi chạy pin: `powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0`
      rồi `powercfg /setactive SCHEME_CURRENT`. Hiện DC = 0x258 (600s), AC = 0 (không bao giờ).
- [ ] Kiểm tra lại: `powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE`
- ⚠️ Không bản vá code nào chạy được job khi máy đang ngủ. Phiên ngủ 23:20–00:03 trùng cửa sổ
      đêm → mất 8 slot bất kể vá gì. Đây là máy cá nhân nên là quyết định của user, không tự đổi.

**Quyết định còn treo: grace cho `preflight` và `maxhold_exit`**
- [ ] Hai job này vẫn để mặc định 1 giây. Cửa sổ của chúng không rộng 5 phút như slot nên
      giá trị đúng khác đi, và có hệ quả giao dịch:
      `preflight` 13:45 ET fail-closed → lỡ nó là **cả ngày không giao dịch**; chạy trễ mà
      vẫn trước 14:05 thì tốt hơn hẳn bỏ (grace hợp lý ~20 phút).
      `maxhold_exit` 09:31 ET đóng vị thế tại RTH open; trễ 5 phút vẫn hơn không đóng.
      Chưa tự quyết vì đây là ngữ nghĩa giao dịch, không phải hạ tầng.

**(c) Cân nhắc thay kiến trúc — chỉ sau khi (a)+(b) chạy ổn vài đêm**
- [ ] Windows Task Scheduler với *"wake the computer to run this task"*. Đây là cơ chế **duy
      nhất** khiến máy TỰ THỨC để chạy job — APScheduler không làm được dù vá thế nào.
      Đánh đổi: mất mutex `_slot_lock` trong tiến trình, phải thay bằng lock trên file/mutex OS.

### Việc vận hành đang treo
- [ ] **Scheduler đang TẮT** — tôi dừng PID 4960 lúc ~00:50 để chạy repair_stops.
      Bật lại trong terminal của user (không phải qua tool, kẻo thành tiến trình con):
      `python -m global_index.run_scheduler --port 4002`

### Files touched
global_index/run_scheduler.py (chưa sửa), TASK.md, SCRATCHPAD.md


---

## Sub-task: B4 naked-position guard (2026-08-03)
Status: PART 2 DONE — PART 1 BLOCKED chờ stop level

### Bối cảnh — phát hiện khi check holding từ IBKR
3 vị thế mở thật (MES LONG / MYM LONG / M2K SHORT, cluster roska4_swing, entry_day 2026-08-03)
đang **không có STP nào**. `openTrades()` = 0, file lưu `stop_price: null, stop_order_id: null`.

Root cause traced: `send_order` đọc ra `status=Cancelled` cho cả 3 lệnh ĐÃ FILL
(reqExecutions có execId/permId, `ib.trades()` = Filled). Gate `status in (FILLED, PARTIAL)`
ở runner.py chặn khối STP → không đặt stop, không log, **không báo động** (log lỗi nằm trong
chính gate đó). B3 lần chạy sau chỉ so inst/direction/contracts → báo "match", không ai biết.

### Completed — Phần 2 (guard)
- [x] `broker.py`: `Broker.has_working_stop(inst)` — concrete, mặc định raise NotImplementedError
      (broker không trả lời được thì B4 chỉ cảnh báo, không đặt mù). MockBroker → False.
- [x] `ibkr_broker.py`: `has_working_stop()` — `reqAllOpenOrders()` + `openTrades()`,
      lọc symbol + orderType STP/STP LMT + status chưa terminal. reqAllOpenOrders trước để
      thấy cả order của clientId khác / process trước.
- [x] `runner.py`: khối B4 sau vòng ORPHAN của B3 + `self._b4_naked_stops`.
      Vị thế khớp cả 2 phía nhưng `stop_order_id is None` → đặt bù nếu biết `stop_price`
      VÀ chắc chắn chưa có stop đang chạy; ngược lại CRITICAL "B4 NAKED".
      **Không halt entries** — state chắc chắn (2 phía khớp), chặn lệnh mới không cứu được
      vị thế đang mở, và exits vẫn phải chạy.
- [x] `test_stp.py`: +5 test B4.1–B4.5 (đặt bù / chống trùng STP / stop_price=None chỉ cảnh báo
      / broker không verify được thì không đặt / no-harm khi đã có stop)

### Verify — ALL PASS
- [x] test_stp 14/14 (9 cũ + 5 mới) | test_ibkr_injection 14/14 | hmm_stale+operational+event_playback 51/51
- [x] reconcile_gd0 PASS — MES 427t/$5,833 | MNQ 425t/$11,570 | MYM 440t/$6,778 | M2K 428t/$2,554 MATCH
- [x] reconcile_stress PASS — 265 Stress days, 108 enter/match, 157 skip, 0 mismatches

### Completed — Phần 1 (xử lý 3 vị thế trần) 2026-08-03
- [x] Stop level lấy từ `p0c_verify_swing.py`: MES 7627.38 / MYM 53290.39 / M2K 2989.90
- [x] Validate vs market + minTick trước khi gửi (LONG round DOWN, SHORT round UP — luôn ra xa
      market, để làm tròn tick không bao giờ kéo stop lại gần và kích hoạt sớm)
- [x] MES SELL STP @ 7,627.25 GTC orderId=9  | MYM SELL STP @ 53,290.00 GTC orderId=10
      → PreSubmitted, verify lại từ IBKR OK; ghi stop_price + stop_order_id vào live_positions.json
- [x] M2K REFUSE: stop 2,989.90 < market 2,994.10 → SHORT thì BUY STP phải nằm TRÊN giá.
      Stop đã bị xuyên. Quyết định (user): đóng market. Fill BOT 1 @ 2,993.20.
      Lỗ thật $26.00 vs $9.50 nếu STP đã tồn tại → **thiếu stop tốn $16.50 trên riêng lệnh này**.
      Đã xoá khỏi live_positions.json; reconcile MATCH (2 vị thế còn lại).
- [x] MNQ: engine báo LONG entry today nhưng không có vị thế và không có lệnh trong log.
      KHÔNG mở — đây là hiệu ứng P0c #2 (desired_basket replay lúc 19:43 ET nhiều bar hơn lúc
      15:55 ET → rổ khác). Mở tay = bịa lệnh.

### Completed — Phần 3 (root cause + vá gốc) 2026-08-03
- [x] **ROOT CAUSE xác nhận** (ib_insync 0.9.86 `wrapper.py:1097`): `warningCodes` hardcode
      {110,165,202,399,404,434,492,10167} ∪ [2100,2200). Code **10349** là warning của IBKR
      nhưng không nằm trong đó → ib_insync vào nhánh error → `trade.orderStatus.status =
      Cancelled` phía client. IBKR không huỷ; lệnh vẫn khớp. Trade log: PendingSubmit
      00:57:51.327 → Cancelled 00:57:51.345 (18ms) → Filled @2993.20. Runner poll 0.1s → trúng.
      Trigger: `outsideRth=True` + `tif` để trống → IBKR lấy preset ghi đè DAY + phát 10349.
      ⚠️ 10349 ĐÃ có trong `_IBKR_INFORMATIONAL` nhưng set đó chỉ hạ log ở `_on_ibkr_error`,
      chạy SAU khi status đã bị đổi — dập tiếng ồn ở sai tầng.
- [x] `ibkr_broker.py` fix 1: `tif="DAY"` explicit ở `send_order` + cả 2 chân `_handle_rollover`
- [x] `ibkr_broker.py` fix 2: `_verified_status(ib, trade)` + `CANCEL_VERIFY_SECS=5.0`.
      Cancelled/ApiCancelled/Inactive mà `filled==0` → re-poll 5s → `trade.fills` phán
      (execution report chỉ tồn tại nếu khớp thật). Áp cho send_order + 2 chân rollover.
- [x] `test_false_cancel.py` 7/7 — FC1 live case, FC2 orderStatus catch-up, FC3 huỷ thật vẫn
      Cancelled (không "rửa" thành fill), FC4 fill sạch không trả phí delay, FC5 partial giữ qty,
      FC6 weighted avg, FC7 Inactive
- [x] VERIFY: test_ibkr_injection 14/14 | pytest 5 suite 72/72 | reconcile_gd0 PASS (4/4 MATCH)

### ⏳ CHỜ VERIFY LIVE (lệnh thật đầu tiên sau fix)
- [ ] Lệnh entry kế tiếp: kiểm log KHÔNG còn `"not filled — status=Cancelled"`, và nếu
      `_verified_status` cứu được thì phải thấy WARNING `"trusting the execution report"`
- [x] ~~Xác nhận STP được đặt tự động ngay sau fill (stop_price + stop_order_id ≠ null)~~
      ❌ **TIÊU CHÍ NÀY SAI — ĐÃ THAY.** `place_stop` trả về orderId do ib_insync tự đúc
      (`ib.py:654` `orderId = order.orderId or self.client.getReqId()`), vô điều kiện.
      `stop_order_id` KHÔNG BAO GIỜ null → tiêu chí luôn pass, kể cả khi IBKR không có
      lệnh nào. Nó đã "pass" ngày 2026-08-05 trong khi 3 vị thế trần trụi qua đêm.
      **Quy tắc rút ra: nghiệm thu STP phải hỏi IBKR, không hỏi file của chính mình.**
- [ ] THAY BẰNG: sau lệnh entry kế tiếp, chạy `check_open_orders.py` (clientId 88, read-only)
      → số STP đang mở phải bằng số vị thế multi-day, khớp cả inst lẫn hướng
      (LONG→SELL STP, SHORT→BUY STP). Log phải có `place_stop: accepted ... status=PreSubmitted`.

### ~~BLOCKED~~ — Phần 1 (đặt STP cho 3 vị thế hiện tại) — DONE, giữ để tham chiếu
- [ ] Cần stop level: `python -X utf8 p0c_verify_swing.py --port 4002 --client-id 92`
      ⚠️ B4 KHÔNG tự cứu được 3 vị thế này: `stop_price` cũng `None` (gate không mở nên không
      field nào được set) → B4 chỉ CẢNH BÁO ở lần khởi động runner kế tiếp, phải đặt tay.
      Sanity-check trước khi gửi: LONG cần stop < giá thị trường, SHORT cần stop > .

### Next steps
- [ ] Cân nhắc bracket order cho entry: stop nằm sẵn trên server IBKR từ lúc submit, không phụ
      thuộc đọc status → xoá hẳn khoảng trần giữa fill và lúc đặt STP. `_verified_status` chỉ
      thu hẹp khoảng đó, không xoá được.
- [ ] Rà các đường khác cũng đọc `orderStatus.status` trực tiếp (`get_order_status` dùng cho B3)
      — cùng lớp lỗi, chưa vá.
- [ ] Slippage OPEN của 3 lệnh 2026-08-03 không được ghi (gate chặn) → slip_stats thiếu 3 mẫu

### Key decisions
- B4 không halt entries: khác B3 (state uncertainty → halt). Ở đây state chắc chắn, chỉ thiếu
  bảo vệ; halt không giảm rủi ro của vị thế đang mở mà lại dừng cả hệ thống.
- Không đặt STP bù một cách mù: hai STP cùng contract cùng fire → đóng 2 lần → lật chiều.
  Không verify được thì cảnh báo, không đoán.

### Files touched
global_index/broker.py, global_index/ibkr_broker.py, global_index/runner.py,
global_index/test_stp.py, SCRATCHPAD.md

---

## Sub-task: Order-flow feasibility + intraday pressure probe — 2026-08-03
Status: DONE — orderflow branch CLOSED; data bug found (worth more than the probe)

### Route taken (each step killed the next by measurement, not opinion)
- [x] **Orderflow as SIGNAL filter — rejected on HORIZON.** Measured holds:
      STRESS_MID 152min | STRESS_ORB 158 | GF_SHORT 180 | ORB 350 | PE_SHORT 1825 |
      TREND_FOLLOW 6925 (88% overnight, 61% MAX_HOLD). Orderflow is seconds-to-minutes.
      Nothing in the system trades at that horizon. (User caught this before I did.)
- [x] **Orderflow for EXECUTION — rejected on measured value.** `execution_ceiling.py`:
      entry-side prize vs bar VWAP = **+$1,219** over 1,292 trades / 6 years = $0.94/trade.
      Exit side -$7,877 (model already fills better than VWAP). Pre-committed rule was
      <$1,000 -> close. Not worth $63-278 data + build.
- [x] **Data availability mapped (Databento, metadata only — $0 spent):**
      CME futures orderflow: mbp-10 $435/yr/instrument, 4-instrument 5yr ~$8,700 — out.
      Stocks, ORB-window slice, 150 days: tbbo $26 / mbo $119 / mbp-10 $174.
      **DBEQ.BASIC is NOT consolidated** — only 4 small venues (NYSE Texas, NYSE
      National, IEX, MIAX Pearl). No consolidated equity feed exists before 2023-03-28.
      Live runtime (5-min cron) cannot execute sub-minute regardless.
- [x] **5-min pressure probe — DEAD.** `intraday_pressure/probe_5min_pressure.py`.
      4.28M bar-obs, 37 tickers, 2017-2024, day-clustered CIs, pre-committed hurdle
      $0.034 gross at h>=10min. **0 of 20 cells cleared.**

### THE ACTUAL FINDING — corrupt META block
- [x] The probe's apparent edge (mean +5.894c vs median +0.500c) was **100% data corruption**.
      Top 0.1% of obs = **533% of total profit**; 814 of top 856 were META with a median
      "move" of **2,154% of price in 10 minutes**.
- [x] **META: 5,157 corrupt 5-min bars over 148 trading days, 2021-06-30 .. 2022-01-28.**
      Close ~$12-16 instead of ~$300-380. ONLY META, no other ticker.
      In `window_debug_5min.pkl` -> feeds window_debug, stress_orb_stk_sim, event index.
- [x] **Baseline impact NEGLIGIBLE**: 1 trade (GF_SHORT, entry $12.62), **-$34 of $33,550**.
      Corrupt prices made META fail the strategies' own filters rather than fire fake trades.
- [x] **Gate weakness exposed**: `|pct_return|>25%` is a RATIO test, so it MISSES two-sided
      corruption (entry ~$14 -> exit ~$14 looks normal). Caught 1 of 4 corrupt META events.
      **3 corrupt events survive into the 267-event clean population AND into the 144-event
      primary cell of the auction-imbalance study.**

### Next steps
- [ ] **Add a price-LEVEL sanity gate** (entry_px vs ticker rolling daily median, >50% dev)
      alongside the existing ratio gate
- [ ] **Re-run the auction-imbalance study after the gate fix** — it was already MONITOR and
      already fragile to 5 events (QCOM), so 3 corrupt events are not obviously ignorable
- [ ] Optional: investigate SAFETY_MODE (-$78.94/trade) and CIRCUIT_BREAKER (-$23.73/trade)
      exit fills modelled BETTER than VWAP — direction is backwards for forced liquidation

### Files added (research only, production untouched)
intraday_pressure/probe_5min_pressure.py, intraday_pressure/FINDINGS.md,
intraday_pressure/pressure_probe.parquet,
orb_stocks/imbalance_research/execution_ceiling.py (+ .parquet),
orb_stocks/imbalance_research/check_databento_imbalance.py

---

## Sub-task: NKD timezone + cluster gate + night slots (2026-08-03)
Status: CODE DONE — chờ verify live phiên JST 04/08

### Bug 1 — trộn múi giờ frozen/live (ĐÃ VÁ)
`run_live_day.py:166` tz_convert parquet NKD sang Asia/Tokyo, `_strip_tz` bỏ tz → nửa frozen
là **JST-naive**. Bar IBKR về là **ET-naive**. `_concat_nkd_live` ghép thẳng → một index hai
đồng hồ. JST = ET + 13h (hè) / 14h (đông).

**Đo thật 2026-08-03:** 1050/1590 bar live trùng nhãn với bar frozen và ghi đè (`keep="last"`),
sai giá ~900–1000 điểm. Ví dụ nhãn `2026-08-03 03:00`: frozen 64,700.00 (03:00 JST) vs
live 63,785.00 (03:00 ET). Hỏng đúng cửa sổ gần nhất mà `desired_position()` dùng để quyết định.

- [x] `_to_session_naive()` — đưa bar live về đồng hồ JST trước khi concat. Qua tz thật
      (không hardcode offset) vì JST−ET đổi theo DST. Fallback `ambiguous=True` cho giờ lặp DST.
- [x] `test_nkd_tz.py` 8/8 — có test đối chứng dựng lại đường cũ để chứng minh không tautology
- [x] Docstring cũ ghi "(both tz-naive ET after strip)" — SAI với nửa frozen, đã sửa
- [x] **Data trên đĩa KHÔNG hỏng**: `update_ibkr_daily.py:104-119` chuẩn hoá cả bar fetch lẫn
      parquet về ET-naive trước khi splice. Corruption chỉ sống trong RAM một lần chạy. Không
      phải rebuild gì.
- ⚠️ **Kết quả P0c MNKD 2026-07-28 VÔ HIỆU** — cả hai vế so sánh dùng chung concat hỏng nên
      chúng khớp nhau. L10 lần nữa: consistency ≠ correctness. Phải verify lại.

### Bug 2 — NKD không bao giờ chạy trong cửa sổ của nó (ĐÃ VÁ)
`between_time("14:00","15:55")` áp trên đồng hồ của từng instrument. NKD `session_tz=Asia/Tokyo`
→ cửa sổ thật là **14:00–15:55 JST = 01:00–02:55 ET**. Scheduler chỉ có slot 09:31/13:45/14:05/
14:10→15:55 ET. `run_live_day` là subprocess chạy-rồi-thoát, nên **từ 15:55 ET tới 09:31 ET hôm
sau không có process nào tồn tại** — cửa sổ NKD nằm trọn trong khoảng chết.

Dữ liệu thì đủ lúc 14:05 ET (đo được: 116/116 bar cửa sổ JST, `entry_day` khớp `today_norm`),
nhưng vào lệnh thì trễ **11 tiếng** so với bar tín hiệu. Tham chiếu quy mô: Option C audit đo
lệch 13–105 phút = **−$9,112 (−20.2%)**.

- [x] `signal_layer.generate_today_signals(active_clusters=...)` — mặc định `None` = tất cả
      (mọi caller cũ không đổi hành vi)
- [x] `_mark_held_unchanged()` — cluster bị gate thì vị thế đang giữ được đánh dấu "y nguyên",
      KHÔNG bỏ trống. Bỏ trống = `diff_desired_vs_held` L110-112 đóng sạch. Dùng lại đúng cơ
      chế nhánh C4 đã có; dedupe luôn 2 chỗ C4 copy-paste.
- [x] ATR chỉ tính cho cluster đang active (slot đêm 5 phút/lần, không trả phí resample 8 năm)
- [x] `run_live_day.py --clusters swing,nkd,stress|all`
- [x] `run_scheduler.py`: 22 slot `NKD_NIGHT_0110..0255` (01:10–02:55 ET, mỗi 5 phút),
      `--clusters nkd`. Bắt đầu 01:10 không phải 01:00 vì `backtest_swing_tf` cần ≥2 bar —
      cùng lý do Rổ 4 bắt đầu 14:10.
- [x] `_prev_bday()` + `prev_preflight=True`: slot đêm chạy TRƯỚC pre-flight 13:45 của chính
      ngày đó → flag hôm nay luôn None → fail-closed sẽ skip vĩnh viễn. Dùng flag của ngày làm
      việc trước (13:45 ET hôm trước, ~11h trước đó = bản cập nhật mới nhất tồn tại lúc 01:10).
- [x] Slot 14:05–15:55 giữ NKD active → exit NKD vẫn chạy ban ngày
- [x] **Pre-flight flag persist ra đĩa** (`global_index/preflight_state.json`, atomic write,
      giữ 7 ngày). `_preflight_ok` vốn chỉ nằm trong RAM — sống được khi mọi consumer chạy
      14:05–15:55 cùng đời process với pre-flight 13:45. Slot đêm đọc flag của NGÀY TRƯỚC nên
      dict rỗng sau mỗi lần restart ⇒ fail-closed vĩnh viễn: feature trông như đã wire nhưng
      không bao giờ bắn. Persist là ghi lại sự kiện đã xảy ra, không phải đoán — entry vẫn key
      theo ngày nên file cũ không thể cấp phép cho ngày nó không nêu tên.
- [x] Seed `preflight_state.json` = {"2026-08-03": true} — chép từ log đã verify:
      `scheduler_0803.log:91  [PRE-FLIGHT] OK — parquet + spy CSV fresh`
- [x] `test_cluster_gate.py` 7/7 — GATE2 là test đối chứng chứng minh key vắng mặt thật sự
      gây exit; GATE6 chứng minh engine bị gate không hề được gọi

### Verify
- [x] pytest 87/87 (cluster_gate 7 + nkd_tz 8 + false_cancel 7 + stp 14 + hmm_stale 42 + ...)
- [x] test_ibkr_injection 14/14
- [x] scheduler đăng ký 47 job, tz America/New_York; 01:10 ET = 14:10 JST = 12:10 VN;
      02:55 ET = 15:55 JST = 13:55 VN — khớp đúng cửa sổ
- [x] reconcile_gd0 PASS (MES 427t/$5,833 | MNQ 425t/$11,570 | MYM 440t/$6,778 | M2K 428t/$2,554)
- [x] reconcile_stress PASS (265 Stress days, 108 enter/match, 157 skip, 0 mismatch)
- [ ] reconcile_nkd — đang chạy nền
- ⚠️ `test_rollover.py::test_ro6_maxhold_then_rollover_no_conflict` FAIL — **hỏng sẵn ở HEAD**
      (verify bằng git worktree tại HEAD, cùng lỗi B3 MISMATCH). Không phải do session này.
      Chưa điều tra.

### Đã sửa — chồng job giữa các slot (2026-08-03)
Slot cách 5 phút, một lần chạy mất ~5,5 phút (đo: connect 12:35:16 → disconnect 12:40:44)
⇒ 2 process cùng lúc, cùng `clientId=1`, đụng nhau ở IBKR. Đây là lỗi P0C_1440/1450 trong
TASK cũ, ghi "chưa fix".

Hai lỗ, sửa cả hai:
- [x] **PID lock đứng sai chỗ**: `run_live_day.py` gọi `broker.connect()` TRƯỚC khi
      `FuturesRunner.__init__` giành E1 lock. Process chồng lấn kịp connect (đụng clientId)
      rồi mới chết vì lock. Fix: giành lock ngay trước connect → thoát trước khi chạm IBKR.
- [x] `_acquire_lock` cho phép **cùng PID** giành lại (run_live_day khoá sớm, FuturesRunner
      khoá lần nữa) — nếu không thì mọi lần chạy đều tự abort trên lock của chính mình.
- [x] **Mutex tầng scheduler** `_slot_lock` trong `_live_day_body` → không spawn process thừa
      ngay từ đầu. `max_instances` KHÔNG dùng được: APScheduler áp per job id, mà mỗi slot là
      một job riêng. Mutex phủ mọi slot, cả ngày lẫn đêm, và cả slot thêm sau này.
- [x] Skip là đúng chứ không mất gì: `diff_desired_vs_held` idempotent (vị thế đang giữ →
      `cur != None` → không vào lại), slot kế làm đúng phần việc đó.
- [x] `test_slot_overlap.py` 6/6 — có test khẳng định skip phải **tức thì** (<0.10s), không
      phải xếp hàng rồi chạy đúp; và test guard không bị kẹt sau khi body raise.

### Next steps
- [ ] Verify live slot đêm đầu tiên (04/08, 12:10–13:55 giờ VN): NKD có được đánh giá trong
      cửa sổ không, MES/MYM có bị đụng không (phải KHÔNG)
- [ ] Verify lại P0c MNKD trên dữ liệu sạch
- [ ] `test_ro6` hỏng sẵn — điều tra riêng
- [ ] Đo $ thật của khoảng lệch 11h (kiểu Option C audit) để biết slot đêm đáng giá bao nhiêu

### Files touched
global_index/signal_layer.py, global_index/run_live_day.py, global_index/run_scheduler.py,
global_index/test_cluster_gate.py, global_index/test_nkd_tz.py

---

## Sub-task: Cluster cap bị bóp theo mức chỉ số (chẩn đoán, 2026-08-04)
Status: DIAGNOSED — chờ quyết định, KHÔNG tự sửa

### Triệu chứng
Slot đêm NKD chạy đúng, sinh candidate hợp lệ mỗi lần, nhưng `entries=0` mọi slot.
`desired_position()` → LONG entry=63,575.00 stop=63,478.39 entry_day=2026-08-04, guard entry_day PASS.
Bị chặn ở `MultiClusterGuard.admits` — gross 5.87% > cap 2.0%.

### Số đo
| | |
|---|---|
| NKD daily ATR14 (04/08) | 2,346.07 điểm |
| `risk_sized` = 1 × 2.5 × 2346.07 × 0.5 | $2,932.59 |
| % của ACCOUNT $50,000 | 5.87% (cap `global_nkd` 2%) |
| % của equity thật $995,344 | 0.29% |
| Account cần để 1 MNKD lọt sleeve 2% | $146,630 |

Lịch sử `risk_sized` (median/năm) và tỉ lệ vượt cap $1,000:
2018 $414/0% · 2019 $350/0% · 2021 $578/0% · 2023 $572/0% ·
2024 $841/27.6% · 2025 $881/33.0% · **2026 $2,061/94.1%**

Phân rã 2019→2026: index level ×2.85 · ATR %giá ×2.06 · ATR điểm ×5.90 (tích của hai).

### Rổ 4 cũng đang bị bóp (chậm hơn)
`risk_sized` cả 4 mã cùng chiều, % của ACCOUNT $50,000 (cap gross 5%):
2017 1.7% · 2019 3.1% · 2023 5.5% · **2026 10.8%** → chỉ còn chỗ cho ~2/4 mã.

### Nguồn gốc con số 2%
- `net_exposure_multi.py` docstring: *"roska4_stress and global_nkd (2%) remain
  ESTIMATES — calibrate during paper trading"* → **chưa bao giờ được sweep**.
- `DECISIONS.md:77`: neo vào giả định *"1 MNKD ATR risk ≈ $437"* = **percentile 22.6%**
  của toàn bộ lịch sử, lấy từ giai đoạn yên nhất 2018–2019. Thực tế hôm nay gấp 6.7×.

### Kết luận — KHÔNG phải lỗi cap
`risk_sized` là đô-la thật đang chịu rủi ro; chặn ở 2% tài khoản là quản trị rủi ro ĐÚNG.
Vấn đề là **độ hạt**: 1 hợp đồng micro Nikkei giờ rủi ro nhiều hơn cả sleeve, và không có
hợp đồng nào nhỏ hơn MNKD. Nguyên nhân gốc: **cơ sở sizing $50,000 đứng yên trong khi thị
trường tăng 2–3×**, nên sức chứa hệ thống co lại đều theo năm. Đây là câu hỏi QUY MÔ VỐN,
không phải câu hỏi hàng rào rủi ro.

⚠️ **Đã suýt sai**: đề xuất ban đầu "neo cap theo notional/ATR% thay vì $ tuyệt đối" là SAI —
nó chỉ cho lọt một lệnh rủi ro 5.87% tài khoản, tức tăng rủi ro thật dưới danh nghĩa sửa cấu
trúc. Đã rút lại trước khi implement.

### Ba lựa chọn (quyết định của user, chưa làm gì)
1. Nâng sleeve (NKD ≥6%, swing ~11%) — tăng rủi ro thật trên nền $50k; trần DD 15% dùng chung
   toàn tài khoản nên PHẢI đo, không đoán.
2. Nâng cơ sở sizing khỏi $50,000 — chính là câu hỏi scaling treo sẵn trong SCALING_ANALYSIS.md
   (ngưỡng n=2 ≈ $55,784, trần n=1 là cố ý). Equity thật $995k thừa sức.
3. Chấp nhận NKD ngủ đông tới khi biến động Nikkei hạ (mất ~25% số vị thế trong IS).

### Nếu đổi cap thì phải chạy lại gì
- **KHÔNG cần**: reconcile gd0/stress/nkd/swing_desired — so ở mức từng mã, cap không tham gia.
- **Cần**: `deploy_sim`. Nhưng cap chỉ tác động ở tầng `replay()` (deploy_sim.py:59-94), còn
  `backtest_basket`/`backtest_swing_tf` (line 179/183/194) độc lập với cap → sweep N giá trị cap
  chỉ cần MỘT lần backtest rồi gọi `replay()` N lần. deploy_sim hiện không cache tầng 1 nên
  script sweep phải tự giữ `all_trades`.
- **Cập nhật theo**: `backtest_calmar = 1.53` hardcode trong runner.py + generate_replay_snapshots.py
  (sàn degradation), INVARIANTS.md, snapshot.
- ⚠️ **Chi phí thật không phải CPU**: vault OOS 2023–2024 (+$7,404, Sharpe 0.88) đã niêm phong
  VỚI cap 2%. Đổi cap = hệ thống đang chạy không còn là hệ thống đã validate OOS.
- ⚠️ Sweep cap trên chính dữ liệu IS rồi chọn Calmar cao nhất = curve fitting, cùng loại sai lầm
  đã cấm với ema/orb_range/bb_std. Docstring nói "calibrate during paper trading" — bằng quan sát
  paper, không phải fit lại trên backtest cũ.

### Files touched
(chẩn đoán, không sửa code) — TASK.md, SCRATCHPAD.md

---

## Sub-task: Mẫu số rủi ro không nhất quán — phanh cắt lỗ mất tác dụng (2026-08-04)
Status: DONE — đã sửa, verify offline + LIVE

### Bug
Hai hàng rào rủi ro đo trên hai tài khoản khác nhau trong cùng một hệ thống:

| Luật | Đo trên | Ngưỡng thật |
|---|---|---|
| "không lỗ quá 15%" (CircuitBreaker) | equity broker **$995,344** | ≈ $149,000 |
| "NKD không quá 2%" (MultiClusterGuard) | hằng số **$50,000** | $1,000 |
| `net_pnl` dashboard | `cur_eq - account` = 995,275 − 50,000 | **$945,275 lãi ảo** |

Phân kỳ nằm đúng một chỗ:
- `deploy_sim`: `equity = account` ($50k) → `equity += pnl_sized` → `breaker.update(equity)` ✅
- `runner`: `equity = broker.get_equity()` (L504) → H4 `state.equity = _h4_eq` (L1112) →
  `breaker.update(state.equity)` (L1114) ❌ — ghi đè bằng số tuyệt đối của broker

`MultiClusterGuard.account` là field cố định 50_000.0, **không có cơ chế cập nhật** →
guard giữ nền $50k trong khi breaker nhảy lên $995k.

H4 sinh ra có lý do đúng (bắt lãi lỗ nội ngày STRESS_MID cho HALT_DAY) — sai ở chỗ lấy
**giá trị tuyệt đối** thay vì **phần chênh lệch**.

### SIM (chạy trước khi sửa) — scratchpad/sim_breaker_base.py
Cùng một đường lãi lỗ bằng đô-la, hai mẫu số:

| kịch bản | lỗ | designed ($50k) | live ($995k) |
|---|---|---|---|
| MaxDD backtest fit_C | $2,789 | HALT_DAY 5.6% | OK 0.3% |
| hard_dd → HALT | $7,500 | **HALT** 15.0% | OK 0.8% |
| mất 60% tài khoản | $30,000 | HALT 60.0% | OK 3.0% |
| **mất TOÀN BỘ $50,000** | $50,000 | HALT 100% | **HALT_DAY 5.0%** |

Mức lỗ đầu tiên khiến phanh bật: designed HALT_DAY=$2,000 / HALT=$7,500 —
live HALT_DAY=$40,000 / HALT=$149,500. **Lỏng 20×; phanh cứng thực tế không tồn tại.**

### Vì sao $995k không phải là vốn
Đó là số IBKR nạp sẵn cho tài khoản paper, không phải vốn phân bổ cho chiến lược.
Hệ thống giao dịch 1 hợp đồng micro, thiết kế + backtest cho $50,000. Lấy equity broker
làm nền nghĩa là hàng rào rủi ro co giãn theo một con số ngẫu nhiên của broker.

⚠️ Tỉ số (Calmar/Sharpe) KHÔNG bị ảnh hưởng — tử và mẫu cùng co giãn nên bất biến theo
quy mô. Chỉ các **ngưỡng tuyệt đối** hỏng: DD halt, HALT_DAY, net_pnl.

### Hướng sửa
Hệ thống tự giữ sổ: `system_equity` bắt đầu ở ACCOUNT, cộng dồn lãi lỗ. Equity broker chỉ
dùng lấy **delta** (giữ nguyên mục đích H4) và để đối chiếu — không làm nền tính rủi ro.
Vì mỗi slot là process chạy-rồi-thoát nên `system_equity` + `last_broker_equity` phải được
persist qua live_positions.json.
⚠️ `peak_equity` đang persist = $995,582 — số rác, phải reset về nền hệ thống.

### Liên quan: cap NKD (sub-task trên) — TÁCH BẠCH
Sửa bug này **không** làm NKD lọt cap. Ở nền $50,000, 1 hợp đồng micro Nikkei vẫn chiếm
5.87% > 2%. Đó là kết luận đúng, không phải bug. Hai chuyện khác nhau:
- **Bug** (mục này): mẫu số mâu thuẫn → sửa, không cân nhắc.
- **Quyết định**: $50,000 có còn đủ cho Nikkei ở mức 64,000 không → thuộc về user.

### Phân tách chu kỳ vs cấu trúc (trả lời "phải nâng vốn mãi sao")
- Biến động Nikkei hiện 3.64% vs trung bình 2018-2025 **1.64%** → gấp **2.23×**, phần này
  HỒI QUY. Ở mức bình thường: risk_sized $1,318, account cần $65,891 (không phải $146,629).
- Phần cấu trúc (chỉ số tăng) được bù bằng **chính lợi nhuận hệ thống**:
  nền $50,000 đóng băng → NKD 2.64% (chặn); nền $50,000 + lãi IS $41,266 = $91,266 →
  NKD 1.44% (**lọt**). Không cần bơm vốn ngoài — cần cho nền vốn cộng dồn.
- ⚠️ **"Nâng nền vốn" ≠ "nâng số hợp đồng"**: nâng n làm danh mục TẬP TRUNG hơn (đã bác bỏ
  có cơ sở, MaxDD n=2 vượt trần 15%); nâng nền cho sleeve làm danh mục ĐA DẠNG hơn (vẫn 1
  hợp đồng/mã, chỉ là nhiều mã lọt hơn). Hai cái ngược hướng nhau về rủi ro, chỉ cái thứ
  nhất từng được đo.

### Đã sửa (runner.py)
- [x] `state.equity` khởi tạo từ `breaker.account` ($50k) thay vì `broker.get_equity()`
- [x] H4 áp **delta** broker (`_h4_delta = _h4_eq - self._last_broker_equity`) thay vì gán
      giá trị tuyệt đối → giữ nguyên mục đích H4 (bắt lãi lỗ nội ngày cho HALT_DAY)
- [x] `breaker.status()` / `final_equity` / `cur_eq` (dump_state, live_state) đổi sang
      `self.state.equity` — hết `net_pnl` ảo $945,275
- [x] Persist `system_equity` + `last_broker_equity` vào live_positions.json (mỗi slot là
      process riêng; thiếu thì equity reset mỗi 5 phút và H4 book lại cùng khoản lãi lỗ)
- [x] Tự loại `peak_equity` cũ ghi theo thang broker (>5× base) → breaker re-peak từ nền hệ thống

### Verify
- [x] `test_equity_base.py` 9/9 — EQ2 phanh cứng bắn ở $7,500; EQ3 mất hết vốn = DD 100%;
      EQ4/EQ5 H4 book delta và KHÔNG book lại; EQ6 HALT_DAY vẫn tới được; EQ7 sổ sống qua
      restart; EQ8 loại peak cũ; EQ9 **giữ** peak hợp lệ ghi theo thang hệ thống
- [x] pytest 108/108 · test_ibkr_injection 14/14
- [x] **run_smoke_test: diff $0.00** — runner == deploy_sim trade-for-trade
      (taken swing 1799/1799 · stress 316/316 · nkd 655/655 · breaker ref=0 run=0)
- [x] **LIVE verified 2026-08-04 00:50–00:56**: migration tự chạy trong slot đêm,
      `discarding persisted peak_equity=$995,607.16` → `system equity=$50,000` →
      `H4: broker delta -5.53 → 49,994.47`. HALT nay bắn ở **$7,500** (trước: $149,337).
      22/22 slot đêm completed OK, không traceback.

### Files touched
global_index/runner.py, global_index/test_equity_base.py, TASK.md, SCRATCHPAD.md

---

## Sub-task: Đo nền vốn $150k — KẾT LUẬN GIỮ NGUYÊN $50,000 (2026-08-04)
Status: DONE — đã đo, bác bỏ việc nâng nền vốn

### Câu hỏi
Paper trade cần chạm được mọi nhánh, nhưng ở nền $50,000 cụm NKD bị cap chặn 94% số ngày
năm 2026 → đường thực thi NKD không bao giờ được chạy thật. Nâng nền vốn có phải là cách?

### Tiêu chí chọn (KHÔNG phải "Calmar cao nhất")
Tỉ lệ ngày bị cap chặn năm 2026 phải khớp thời kỳ đã validate (2018-24 @ $50k):

| vốn | NKD 2018-24 | NKD 2026 | Rổ4 2018-24 | Rổ4 2026 |
|---|---|---|---|---|
| $50,000 | 5.5% | **94.1%** | 60.3% | **100.0%** |
| $100,000 | 0.5% | 53.9% | 6.3% | 64.1% |
| $125,000 | 0.0% | 30.9% | 1.7% | 28.1% |
| $150,000 | 0.0% | **5.9%** | 0.9% | **1.3%** |

⚠️ **Không có nền vốn nào phục hồi được cả hai cụm**: NKD cần $150k (5.9%≈5.5%), Rổ 4 cần
$100k (64.1%≈60.3%). Nikkei tăng mạnh hơn chỉ số Mỹ nên hai cụm trôi khác tốc độ.

### Đo thật — deploy_sim (frozen_sim, spy_daily.csv, end 2024-12-31, n=1)
| | $50,000 | $150,000 |
|---|---|---|
| net | $46,683 | $55,720 (+19%) |
| **Calmar** | **1.99** | **1.40** (−30%) |
| Sharpe | 1.90 | 1.60 |
| PF | 1.57 | 1.51 |
| MaxDD | $3,390 | **$5,767 (+70%)** |
| swing taken/rej | 1799 / 697 | **2488 / 8** |
| nkd taken/rej | 655 / 46 | **701 / 0** |

### KẾT LUẬN — GIỮ $50,000
**Calmar 1.40 < sàn degradation 1.53** (hardcode trong runner.py +
generate_replay_snapshots.py) → cấu hình $150k **trượt chính cửa chất lượng của hệ thống**.

MaxDD phình 70% trong khi lợi nhuận chỉ tăng 19%. Khi rejection rơi 697→8, hệ thống nhận gần
như mọi tín hiệu kể cả loại `entry_priority_key` xếp hạng thấp, và giữ cả 4 chỉ số tương quan
cùng lúc — đúng thứ làm DD phình.

**Cap KHÔNG phải chướng ngại vật, nó đang làm việc thật.** Docstring ghi 2% là "ESTIMATE,
calibrate during paper" — nhưng "chưa được sweep" ≠ "đặt sai". Đo xong thì nới ra là hỏng.

### Hệ quả cho paper phase
- NKD không vào lệnh = **hành vi đúng**, không phải bug
- Muốn kiểm đường thực thi NKD → làm **riêng** như P0c (đặt tay 1 lệnh MNKD ngoài luồng
  chiến lược, ghi rõ là kiểm plumbing, không tính vào P&L paper). KHÔNG bóp méo hệ thống
  để tiện test.
- Tiền lệ đêm nay: chính vì đặt STP tay cho MES/MYM mà phát hiện `send_order` đọc sai trạng
  thái — thứ chờ hệ thống tự làm thì không bao giờ lộ.

### Câu hỏi còn mở (không cấp bách)
- Rổ 4 bị chặn 100% số ngày năm 2026 (vs 60.3% thời validate) — chặt hơn hẳn thiết kế.
  Chưa đo tác động. Nếu muốn xét thì phải sweep riêng cap `roska4_swing`, không phải nền vốn.

---

## Sub-task: Sweep RIÊNG cap NKD (2026-08-04) — ĐÃ ÁP DỤNG 6%
Status: DONE — commit f8a1f13

### Vì sao phải đo lại
Phép đo $150k gộp HAI thay đổi: nó nới cap của **mọi** cụm cùng lúc. Rejection Rổ 4 rơi
697 → 8, và chính chỗ đó làm MaxDD phình $3,390 → $5,767. Chưa ai thử nới RIÊNG cap NKD.

### Kết quả — scratchpad/sweep_nkd_cap.py
Rổ 4 giữ nguyên 5%/4.4% (swept optimum). Chỉ đổi `global_nkd`. Nền vốn $50,000 không đổi.

| nkd cap | $cap | net$ | Calmar | Sharpe | MaxDD$ | swing t/r | nkd t/r |
|---|---|---|---|---|---|---|---|
| **2% (hiện tại)** | 1,000 | 46,683 | 1.99 | 1.90 | **3,390** | 1799/697 | 655/46 |
| 3% | 1,500 | 47,078 | 2.01 | 1.87 | 3,390 | 1799/697 | 686/15 |
| 4% | 2,000 | 48,091 | 2.05 | 1.90 | 3,390 | 1799/697 | 695/6 |
| **6%** | 3,000 | **48,453** | **2.07** | 1.90 | **3,390** | 1799/697 | **701/0** |
| 8% | 4,000 | 48,453 | 2.07 | 1.90 | 3,390 | 1799/697 | 701/0 |
| 12% | 6,000 | 48,453 | 2.07 | 1.90 | 3,390 | 1799/697 | 701/0 |

**MaxDD đứng yên $3,390 qua MỌI mức cap.** Calmar tăng 1.99 → 2.07. Sharpe không đổi.
Rejection Rổ 4 giữ nguyên 697 — cụm swing không bị đụng.

→ Xác nhận bằng số lập luận gốc trong docstring `net_exposure_multi.py`: NKD lệch múi giờ
~13h, tương quan chéo +0.225, **không tham gia vào đợt sụt tệ nhất**. Cap 2% chỉ chặn lệnh
mà không đổi lại được một đồng bảo vệ nào.

### Vì sao 6% KHÔNG phải curve fitting
1. Không chọn cực đại — từ 6% trở đi mọi số **bão hoà** (701/0, y hệt ở 8% và 12%).
   6% là chỗ ràng buộc NGỪNG CẮN, không phải chỗ tối ưu.
2. MaxDD bất biến → không có đánh đổi rủi ro/lợi nhuận nào để tối ưu.
3. Tiêu chí là "để cụm giao dịch đúng tín hiệu của nó", không phải "tìm số cho Calmar đẹp".

### ⚠️ Hai cảnh báo trước khi đổi
1. **Biên rất mỏng cho chế độ hiện tại.** Sweep chạy trên 2018-2024 khi `risk_sized` NKD là
   $350-900. Hôm nay **$2,846** — ở cap 6% ($3,000) lọt nhưng chỉ dư 5%. Vol nhích là chặn
   lại. Muốn NKD chạy ổn định trong chế độ 2026 thì cần cao hơn 6%, mà cao hơn thì **không
   còn được sweep này chống lưng** (in-sample đã bão hoà từ 6%).
2. **Dải dữ liệu bao trùm kỳ vault 2023-2024.** Chọn cap dựa trên nó là chạm kỳ OOS đã niêm
   phong → cấu hình 6% chưa từng có kỳ OOS sạch.

### ⚠️ SỬA SAI PHƯƠNG PHÁP — số sweep ở trên chạy 1-tick
INVARIANTS dòng 21 bắt buộc **2-tick/side cho mọi verdict**. Bảng sweep phía trên (Calmar
1.99/2.07) và các phép đo $150k (1.40) / no-NKD (1.15) đều chạy 1-tick = **upper bound,
không so được** với baseline chính thức. Sàn thật là **1.57** (2-tick), không phải 1.53.
Hướng kết luận sống sót, biên độ nhỏ hơn.

### Số ĐÚNG convention (2-tick) — cơ sở quyết định
| | cap 2% | cap 6% |
|---|---|---|
| baseline fit_C | $40,919 / 1.66 | **$42,459 / 1.72** MaxDD $3,574 (7.1%) |
| sàn fit_A | $40,642 / 1.57 | **$42,565 / 1.65** MaxDD $3,744 (7.5%) |
| vault 2023-24 | $10,415 / 2.77 | **$10,757 / 2.86** MaxDD $1,899 (3.8%) |
| vault 2025 | $7,371 / 3.39 | **$7,404 / 2.54** MaxDD $3,001 (6.0%) |

`1.66 × (42,459/40,919) = 1.72` khớp chính xác → Calmar tăng **hoàn toàn do lãi thêm**,
MaxDD không đổi. MaxDD tệ nhất $3,744 = 7.5%, chưa chạm WARN 10% ($5,000), cách HALT 15%
($7,500) hơn gấp đôi.

### Quyết định: ÁP DỤNG 6% — tiêu chí là CỔNG INVARIANTS, không phải so 6% với 2%
Cả 4 cổng PASS (baseline + 2 vault đều vượt sàn 1.65). Giữa hai cấu hình đều hợp lệ, tiêu chí
là "cái nào khớp hệ thống đã validate" — ở cap 2% trong chế độ 2026, NKD không vào lệnh được
nên hệ thống đang chạy KHÔNG phải hệ thống đã validate (vốn gồm 655–701 lệnh NKD).

⚠️ Ghi nhận, không phải cổng trượt:
- Biên baseline trên sàn hẹp lại +5.7% → +4.2%
- **Vault 2025 xấu đi mọi thước đo rủi ro** (Calmar −25%, Sharpe −8%, PF −5%, MaxDD +38%)
  đổi lấy +$33. Đây là kỳ gần chế độ hiện tại nhất.
- Sharpe giảm ở CẢ HAI vault. INVARIANTS chỉ gate trên Calmar.
- Cap chọn từ dữ liệu bao gồm kỳ vault → **không có OOS sạch**

### Drift phát hiện khi suy lại sàn (đã sửa cùng commit)
- `runner.py` + `generate_replay_snapshots.py` hardcode **1.53** — INVARIANTS đã deprecate
  1.53 hai lần. Nay cả hai đọc `BACKTEST_CALMAR_FLOOR = 1.65`, kèm lệnh suy lại trong comment.
- `runner.py` nhân bản bảng cap thành literal trong payload dashboard, `global_nkd` còn 2%
  → dashboard báo giới hạn mà guard không còn áp. Nay đọc `self.guard.clusters`.
- `replay_snapshots_data.js` mang `backtest_calmar: 2.04` — **sàn dirty do look-ahead**,
  chưa từng tái tạo sau khi sửa look-ahead. Nay 1.65, cap 6%, 1759 snapshots.

### reconcile_nkd — PASS (chạy nền, xong 2026-08-04)
Phase 1: engine 519t/$13,073 == harness 519t/$13,073, field_mismatch=0
Phase 2: cả 519 trade, entry state OK + exit state OK
VERDICT PASS — chạy trên frozen parquet thuần nên KHÔNG bị ảnh hưởng bởi bug trộn tz đã sửa,
đúng như dự đoán "cap/tz không làm mất hiệu lực reconcile".

---

## Sub-task: Sweep RIÊNG cap roska4_swing (2026-08-04) — XÁC NHẬN GIỮ 5%/4.4%
Status: DONE — đo xong, KHÔNG đổi

### Câu hỏi
Rổ 4 bị cap chặn 100% số ngày năm 2026 (vs 60.3% thời validate) — hiện chỉ giữ được
MES+MYM ($2,123 = 4.25%), còn $377 trống trong khi mã rẻ nhất cần ~$700. Cùng cơ chế
đã giết NKD. Có phải nới cap không?

### Đo — scratchpad/sweep_swing_cap.py
2-tick + spy_daily_live.csv (ĐÚNG convention INVARIANTS lần này). `global_nkd` giữ 6%.
Tỉ lệ gross/net giữ nguyên 5/4.4. **Self-check: dòng 5.0% tái lập chính xác baseline
$42,459 / Calmar 1.72** → script đúng.

| swing cap | net$ | Calmar | Sharpe | MaxDD$ | swing t/r |
|---|---|---|---|---|---|
| 4.0% | 37,952 | 1.71 | 1.69 | 3,201 | 1522/974 |
| **5.0% (hiện tại)** | **42,459** | **1.72** | 1.67 | 3,574 | 1799/697 |
| 6.0% | 41,928 | 1.42 ✗ | 1.49 | 4,281 | 2032/464 |
| 8.0% | 47,673 | 1.26 ✗ | 1.51 | 5,479 | 2287/209 |
| 10.0% | 49,656 | 1.25 ✗ | 1.47 | 5,729 | 2406/90 |
| 12.0% | 50,113 | 1.17 ✗ | 1.44 | 6,217 | 2461/35 |
| 15.0% | 48,813 | 1.14 ✗ | 1.40 | 6,217 | 2488/8 |

✗ = trượt sàn 1.65

### KẾT LUẬN: GIỮ 5%/4.4%
**5% là đỉnh thật** — 4% cho 1.71, 6% rơi xuống 1.42. Mọi mức trên 5% trượt sàn, kể cả
nới đúng 1 điểm phần trăm. Sweep gốc được XÁC NHẬN, không phải lật ngược.

### Đối lập hoàn toàn với NKD — lý do cách chữa không đối xứng
| | global_nkd | roska4_swing |
|---|---|---|
| MaxDD khi nới cap | **bất biến** $3,390 | **tăng đều** $3,201→$6,217 |
| Calmar | tăng rồi bão hoà | **đỉnh đúng ở giá trị hiện tại** |
| Bản chất cap | chặn lệnh, không đổi lại gì | **đang gánh việc thật** |
| Nguồn gốc số | ESTIMATE chưa sweep | swept optimum |

### Khép luôn câu hỏi vốn CHO RỔ 4
Nâng vốn giữ cap 5% = nới cap bằng đô-la: $150,000 × 5% = $7,500 = đúng dòng 15% ở nền
$50k → **Calmar 1.14**. Tức là với Rổ 4, **nhiều vốn hơn làm hiệu suất điều chỉnh rủi ro
XẤU ĐI**. Phân phối chỗ không phải khiếm khuyết — cap đang chọn lệnh tốt hơn qua
`entry_priority_key` và hạn chế phơi nhiễm tương quan.

→ **"Rổ 4 chỉ giữ 2 trong 4 mã" là thiết kế chạy đúng, không phải chỗ cần sửa.**

Cũng xác nhận suy luận loại trừ trước đó (MaxDD phình trong phép đo $150k đến từ phía
Rổ 4) — giờ là đo trực tiếp, không còn là suy luận.

---

## Sub-task: Bug THANG GIÁ live vs parquet (2026-08-04) — ĐÃ SỬA
Status: DONE — commit 03cc53d

### Phát hiện thế nào
Truy câu hỏi "stop loss đã adjust chưa" → phát hiện `desired_basket` trả None cho MES/MYM
(backtest đã đóng, live vẫn giữ vì slot hôm nay bị skip) → soi tiếp thì thấy lệnh MES live
**không có lệnh tương ứng nào trong backtest**.

Replay MES ở 4 mốc cắt (15:10 = đúng phút đặt lệnh / 15:55 / 23:59 / hôm sau):
`desired_position` trả **None ở mọi mốc**. Lệnh live không đến từ engine.

### Nguyên nhân — đo trực tiếp cùng mốc 2026-08-04 15:24
| inst | parquet | IBKR live | chênh |
|---|---|---|---|
| MES | 7,792.25 | 7,780.00 | **+12.25** |
| MNQ | 30,011.50 | 29,922.75 | **+88.75** |
| MYM | 54,316.00 | 54,355.00 | **−39.00** |
| M2K | 3,058.90 | 3,049.70 | **+9.20** |

Parquet = ContFuture + splice offset (back-adjusted). `fetch_bars` = front-month thô.
`_concat_live` ghép `keep="last"` → live ghi đè parquet → bậc nhảy 12–89 điểm ngay cửa sổ
tín hiệu. MNQ 88.75 điểm = 0.30%, thừa sức tạo breakout/EMA-cross giả.

### Sửa — hai nửa, nửa 2 BẮT BUỘC
- [x] `_splice_live` thay `_concat_live`: chỉ nối bar SAU parquet (hết ghi đè lịch sử), dịch
      theo đúng anchor `update_ibkr_daily` (`last_close − first_new_open`), **trả offset ra**
- [x] `to_candidate(price_offset=)`: quy entry/stop về thang thô tại đúng chỗ giá tín hiệu
      thành giá lệnh. Thiếu → stop LONG 7,639.50 vs giá 7,635 → **kích hoạt tức thì**
- [x] `_splice_nkd_live`: đổi đồng hồ JST TRƯỚC rồi mới splice (sai thứ tự thì neo sai bar).
      NKD có khoảng cách thang lớn nhất rổ (+1065.0 tại splice 2026-07-06)
- [x] `price_offsets` mặc định rỗng → mọi caller cũ không đổi hành vi

### Verify
- [x] `test_price_scale.py` 8/8 — PS2 chống ghi đè lịch sử · PS4 anchor là bar splice không
      phải trung bình overlap · PS6 stop không vượt lên trên giá
- [x] pytest 130/130 · injection 14/14 · signal_layer self-test PASS
- [x] reconcile_gd0 PASS · run_smoke_test diff $0.00, cluster counts không đổi

### ⚠️ Hệ quả với các verify cũ
`p0c_verify_swing.py` dùng **cùng hàm concat** nên tái tạo đúng chuỗi hỏng rồi báo "khớp".
Kết quả P0c swing (MYM/M2K 2026-07-30 ✅) **bị vô hiệu** — phải verify lại sau khi sửa.
Cùng số phận với P0c MNKD đã vô hiệu vì bug múi giờ. L10 lần thứ ba trong một phiên.

---

## Sub-task: Sweep chandelier_atr_mult (2026-08-05) — GIỮ 2.5
Status: DONE — đo xong, KHÔNG đổi

### Câu hỏi
Chandelier chiếm 79.5% số lệnh thoát, trung bình −$48.84; MAX_HOLD 15.1% nhưng
+$398.60 — toàn bộ lãi nằm ở MAX_HOLD. Stop chỉ ratchet lên trên entry 1.6% số lần,
98.4% thoát dưới giá vào. Đo MFE: **mọi** lệnh chandelier đều từng có lãi (median
$64.50, p90 $267.40) rồi trả lại hết. Siết dải trượt để giữ phần đó có đáng không?

### Đo — scratchpad/sweep_chand.sh (deploy_sim CLI, không phải harness tự viết)
2-tick + frozen_sim + spy_daily_live.csv + end 2024-12-31 + n=1. `--nkd-mult` giữ 2.5.
**Self-check: dòng 2.5 tái lập chính xác baseline $42,459 / Calmar 1.72.**

| mult | net$ | Calmar | Sharpe | PF | MaxDD$ | swing t/r |
|---|---|---|---|---|---|---|
| 1.0 | 49,845 | 1.16 ✗ | 1.43 | 1.44 | 6,217 (12.4%) | 2469/27 |
| 1.5 | 48,118 | 1.27 ✗ | 1.51 | 1.45 | 5,478 (11.0%) | 2310/186 |
| 2.0 | 43,469 | 1.46 ✗ | 1.52 | 1.44 | 4,315 (8.6%) | 2079/417 |
| **2.5 (hiện tại)** | **42,459** | **1.72** | 1.67 | 1.48 | 3,574 (7.1%) | 1799/697 |
| 3.0 | 37,868 | 1.50 ✗ | 1.65 | 1.48 | 3,653 (7.3%) | 1578/918 |
| 3.5 | 36,684 | 1.96 | 1.76 | 1.53 | 2,702 (5.4%) | 1402/1094 |
| 4.0 | 31,805 | 1.84 | 1.66 | 1.50 | 2,500 (5.0%) | 1270/1226 |
| 5.0 | 24,644 | 1.56 ✗ | 1.60 | 1.45 | 2,287 (4.6%) | 1093/1403 |

✗ = trượt sàn 1.65

### KẾT LUẬN: GIỮ 2.5 — không arm nào ứng cử được, KHÔNG chạy vault
- **net$ và MaxDD đơn điệu** theo mult (đường biên đánh đổi sạch). **Calmar/Sharpe/PF
  nhấp nhô**: 1.46 → 1.72 → **1.50** → 1.96 → 1.84. Hai arm cạnh nhau lệch 0.46 →
  nhiễu của chính thước đo cỡ ±0.2, vì mẫu số MaxDD là **một sự kiện đơn lẻ**.
- 3.5 hơn ở 3/4 chỉ số nhưng chênh Calmar nằm trong nhiễu đó, còn net$ thua rõ 14%.
  Chọn 3.5 = nhặt số đẹp từ mẫu số nhiễu → curve fitting. Vault để **xác nhận** ứng
  viên, không phải để **tìm** ứng viên → không chạy.

### ⚠️ Nhiễu hai chiều — sweep này KHÔNG cô lập được "khoảng trượt"
`mult` vừa đặt khoảng stop **vừa là mẫu số risk$ mỗi lệnh** (`mult × ATR × point_value`).
Nới stop → mỗi lệnh đắt hơn trong ngân sách cụm → gate đá ra từ **27 lên 1,403** lệnh
(56% tín hiệu). Phần net$ giảm khi nới stop có phần đáng kể chỉ do **ít lệnh được vào**.
Rủi ro mỗi lệnh giảm nhưng rủi ro **danh mục** tăng (nhiều vị thế đồng thời) → MaxDD 12.4%.

**Muốn thu phần lãi đang trả lại thì phải TÁCH tham số làm hai** — một hệ số cho stop
ban đầu (định risk$/sizing) + một hệ số riêng cho dải trượt. Đó là sửa thiết kế engine,
phải qua OOS cả hai vault, KHÔNG phải một sweep.

---

## Sub-task: Đọc log scheduler 2026-08-05 — 3 phát hiện
Status: phiên chạy sạch; 3 việc chưa xử

### Phiên hôm nay OK
14:10 ET đóng MES+MYM (MAX_HOLD), fill thuận lợi (MES tốt hơn stop 144.25đ, MYM 1412đ).
Equity 49,994 → **51,851** (+$1,857). 14:40 ET vào MES LONG / MYM SHORT / M2K SHORT,
**cả ba đặt được stop ngay** (orderId 62/66/70) — khác hôm qua.

### 1. `maxhold_exit` 09:31 ET KHÔNG chạy hôm nay
Scheduler tắt 02:55 ET (hết slot NKD đêm), sáng bật lại **09:43 ET** — sau cron 12 phút,
job im lặng bỏ qua. Hai lệnh MAX_HOLD vẫn thoát nhưng qua `run_live_day` lúc **14:10 ET**,
**muộn hơn quy ước backtest 4h40** (mốc 09:30 ET mà INVARIANTS đã cố định).
Gốc: scheduler bật tay mỗi sáng; bật sau 07:31 giờ máy → mất job, **không cảnh báo**.

### 2. 11 slot bị SKIP — đúng thiết kế nhưng mất một nửa nhịp
Mỗi lần chạy 5.5 phút, slot cách 5 phút → cứ một slot chạy thì slot kế bị bỏ.
Nhịp thực **10 phút, không phải 5**.

### 3. G2 HARD lặp mỗi lần chạy
`model 20 months old (fit_end=2024-12-31) — re-freeze immediately` — mức HARD, xuất hiện
ở **mọi** lần chạy, hệ thống vẫn giao dịch. Guard đang bị vô hiệu hoá trên thực tế.

---

## Sub-task: Chi phí skip slot + cắt cửa sổ replay (2026-08-05)
Status: ĐO XONG — chưa triển khai

### Skip KHÔNG mất tín hiệu (trace code)
`desired_position()` chạy lại **toàn bộ backtest trên dữ liệu-đến-hiện-tại**
(swing_tf.py:47) → idempotent, slot sau tái tạo đúng mục tiêu. Stop là `ibi.StopOrder`
GTC **nằm sẵn ở IBKR** (ibkr_broker.py:807) → kích hoạt liên tục, không cần scheduler.
CHANDELIER = 79.5% số lần thoát → **nằm ngoài tầm ảnh hưởng của skip**.

### Phần bị ảnh hưởng: giá vào lệnh (MarketOrder, ibkr_broker.py:514)
Đo trên 2,493 lệnh vào 2018-2024 (scratchpad/slot_delay_cost.py):

| độ trễ | tổng | tb/lệnh | % bị thiệt | p90 xấu |
|---|---|---|---|---|
| 5 phút | $2,769 | $1.11 | 53.7% | $28.50 |
| 10 phút | $5,132 | $2.06 | 53.3% | $36.25 |
| 15 phút | $8,440 | $3.39 | 53.1% | $42.50 |

Trễ 5 phút **không tránh được** (runtime 5.5 phút). Phần **do skip**:
**$5,132 − $2,769 = $2,363 / 7 năm ≈ $338/năm**. 53% bị thiệt = gần như tung đồng xu;
median $2.00 = đúng một tick. Thật nhưng nhỏ.

### Giãn slot 5→6 phút KHÔNG giải quyết
Hiện tại (lưới thực 10 phút): trễ luân phiên 5.4 / 10.4 → **tb 7.9 phút**.
Slot 6 phút (không bỏ slot nào): 5.5 + chờ tb 3.0 → **tb 8.0 phút**. Bằng nhau —
**runtime 5.5 phút mới chi phối**, không phải khoảng cách slot.

### Runtime đi đâu (từ log)
parquet 1s · **fit lại HMM 13s** (n_init=10, model frozen ≤2024-12-31, không bao giờ đổi) ·
IBKR+reconcile 4s · **`run_day` 5 phút 03** · đặt lệnh 8s.
`run_day` = `backtest_swing_tf` phát lại **8 năm × 4 instrument**, gọi `TrendFollowStrategy`
từng bar (_validated_core.py:236) — 3,910 dòng log/lần chạy.

### Cắt cửa sổ — ĐO ĐƯỢC (scratchpad/warmup_confirm.py)
So `desired_position` bản cắt vs bản đầy đủ, 41 mốc as-of × 4 instrument:

| W (phiên) | phép so | khớp | lệch |
|---|---|---|---|
| 20 | 164 | 163 | 1 (MYM 2021-02-04) |
| **60** | 164 | **164** | **0** |
| 120 | 164 | 164 | 0 |

Tốc độ 1 instrument: đầy đủ (2,488 phiên) **86.0s** · W=60 **1.49s** · W=120 **4.62s**
→ 4 instrument ở W=120 ≈ **18.5s** (vs 344s). `run_day` xuống dưới 1 phút → hết skip,
độ trễ tb 7.9 → ~3 phút.

### Cơ chế — vì sao cần ~60 phiên (đọc từ code, không phải mò)
Toàn bộ phụ thuộc lịch sử của engine nằm ở ĐÚNG HAI chỗ:
- `datr = daily_atr_series(df)` (_validated_core.py:209, dùng ở :290) — ATR ngày cho dải
  chandelier, làm trơn kiểu Wilder → cần ~56 phiên để hội tụ
- `pos` — vị thế đang mở, tối đa **5 ngày** (MAX_HOLD)

EMA + ATR sinh tín hiệu vào lệnh tính TRONG MỘT NGÀY trên bar 5 phút
(`hist = bars5.loc[:idx[n]]`, `bars5 = b5[day]`, :344-348) → **không cần lịch sử**.
`hl`/`b5`/`ts` độc lập theo ngày (`groupby`, :219). Vòng lặp carry đúng một biến: `pos`.

→ Nhu cầu thật ~60 phiên. Đo thực nghiệm ra đúng vậy (20 lệch, 60 khớp).
**Cơ chế và số đo trùng nhau.** Chọn **250 phiên (1 năm) = dư 4 lần.**

| N phiên | 4 instrument | run_day |
|---|---|---|
| hiện tại (2,488) | 331s | 5m03 |
| 250 | ~33s | **~1m07** |

### Các phương án đã cân nhắc và LOẠI
| cách | thời gian | cache đĩa | vì sao loại |
|---|---|---|---|
| cache prep ra đĩa | 198s | **489 MB** | chỉ cắt 42%, biên còn 1 phút; 489 MB phải huỷ đúng lúc |
| checkpoint + replay hôm nay | ~1s | ~1 MB | chính xác nhất nhưng **đổi luồng chạy** `_validated_core.py` + state lưu trữ |
| **cắt 250 phiên ở tầng gọi** | **~33s** | **không** | ĐƯỢC CHỌN — stateless, không đụng engine |
| giãn slot 5→6 phút | — | — | tb 8.0 phút vs 7.9 hiện tại; runtime mới chi phối |

Đo phụ trợ: prep 34.67s (42%) / loop 48.11s (58%) / cache 122 MB per instrument;
ghi đĩa 0.70s, nạp 1.52s. Tức cache prep LÀ net win nhưng không đủ biên.

---

## 🎯 Sub-task: Checkpoint replay — Bước 1-3+5 DONE, Bước 4+6 còn lại
Status: IN PROGRESS — engine xong, chưa nối vào production

### Vì sao chọn checkpoint thay vì cắt cửa sổ
Đọc `backtest_swing_tf`: vòng lặp `for day in days:` carry ĐÚNG một biến `pos`.
EMA + ATR sinh tín hiệu tính TRONG MỘT NGÀY trên bar 5 phút (`hist = bars5.loc[:idx[n]]`,
:344-348) → không cần lịch sử. `hl`/`b5`/`ts` độc lập theo ngày (`groupby`, :219).
Chỉ còn `datr` (ATR ngày, Wilder) cần lịch sử — mà tính lại chỉ tốn **0.18s**.

→ Seed `pos` + cấp `datr` = **chính xác tuyệt đối**, không phải xấp xỉ như cắt cửa sổ.

| cách | 4 instrument | cache đĩa | chính xác |
|---|---|---|---|
| hiện tại | 331s | — | — |
| cache prep ra đĩa | 198s | 489 MB | giống hệt, nhưng biên chỉ 1 phút |
| cắt cửa sổ W=120 | 18.5s | không | **xấp xỉ** |
| **checkpoint** | **~5s** | **~0** | **chính xác** |

Đo phụ trợ: prep 34.67s / loop 48.11s / `daily_atr_series` 0.18s / hash toàn df 0.54s /
nạp parquet 0.35s / pickle cache 122 MB (ghi 0.70s, nạp 1.52s).

### Bước 1 ✅ `0bd07c4` — vá khoá `_swing_cache`
`id(df)` = địa chỉ bộ nhớ; df tạm bị thu hồi → df kế trúng cache của khung khác, IM LẶNG.
Fix: entry giữ tham chiếu `(df, cache)` — hai object sống không thể chung địa chỉ, đó là
bảo đảm của CPython chứ không phải xác suất. **Không dùng hash nội dung** (0.54s/lời gọi,
WFO gọi hàng trăm lần = đúng cái cache sinh ra để tránh).
⚠️ `df = df.assign(...)` gán đè → phải đổi tên `dfg`, nếu không giữ nhầm bản copy.
Regression: 41 mốc trên lát cắt tạm, cache-hoạt-động == cache-xoá, **có cả `stop`**.

### Bước 2 ✅ `c09f69d` — `datr=` injectable
`_swing_cache(df, datr=None)` + `backtest_swing_tf(..., datr=None)`.
Khoá thành `(id(df), id(datr))`, entry giữ cả hai tham chiếu — nếu không thì cùng df với
`datr` khác sẽ nhận entry cũ = tái lập lỗi Bước 1 ở chỗ mới.
Kiểm: datr=None vs inject → 615 lệnh giống hệt · cùng df hai datr khác → 615 vs 462 + 2
entry cache · caller cũ gọi 2 lần → cache 1→1 (WFO không mất hiệu năng).

### Bước 3 ✅ `7c5e828` — `resume_pos=` + `resume_after_day=`
`pos = dict(resume_pos)` — **copy**, vì vòng lặp ratchet `pos["stop"]`/`["extreme"]` tại chỗ.
Thiếu copy → gọi lần 2 từ cùng checkpoint ra kết quả khác lần 1.
Frozen: 10/10 checkpoint (MES+MNQ, 2018-2023) khớp tuyệt đối, pos cuối trùng, lặp lại ổn định.

⚠️ **Lead-in**: khung phải bắt đầu ≥1 phiên TRƯỚC ngày replay đầu tiên. `_swing_cache` ép
bar đầu khung thành "không gap" (`is_gap_full[0] = False`); cắt đúng ngày resume thì bar
đầu ngày đó mất cờ gap → lệnh đáng lẽ thoát GAP (fill giá mở, xấu hơn) thành CHANDELIER.
**Đọc từ code, CHƯA quan sát được**: 10 checkpoint chạy thêm arm không-lead-in đều KHÔNG
lệch. Cần stop chạm đúng bar đầu của đúng ngày đầu — 10 mẫu không tới. Giữ lead-in là bảo
hiểm rẻ cho cơ chế có thật, không phải nhu cầu đã đo được.

### Bước 5 ✅ `fe093a5` — `global_index/verify_resume.py`
Chạy trên **parquet live** (2017→2026-08-06, gồm vùng repair), so **toàn bộ vị thế có `stop`**:
- MES/MNQ/MYM/M2K: **24/24** (lùi 2,4,6,8,15,25 phiên)
- MNKD: **14/14** (lùi 1..30 phiên) — engine khác, lịch JST, nhãn regime riêng
- Cộng 10 checkpoint frozen ở Bước 3 → **60 điểm so sánh, 0 lệch**
- Mốc lùi 2-8 phiên (vùng production dùng) hầu hết **có vị thế mở** → đường seed thật sự được đi qua

⚠️ **Lỗi trong script kiểm, không phải engine**: `_sessions` dùng `index.normalize().values`
→ quy UTC trước; nửa đêm JST = 15:00 UTC hôm trước → **mọi** phiên MNKD bị gán nhãn sớm 1 ngày.
Hệ quả không chỉ 1 ca báo lệch mà 2 ca "OK" cũng vô nghĩa (so cửa sổ lệch nhau).
Fix: `normalize().tz_localize(None)` giữ giờ địa phương, đúng cách engine làm.
ET **không dính**: 0/2,987 phiên lệch, đã kiểm cả mốc DST.
→ Thêm cột `có-vị-thế`/`trống` vào output: màn hình toàn OK có thể che việc đường seed
chưa bao giờ được đi qua.

### Bước 4 ⏳ CHƯA LÀM — nối vào `run_live_day`
- [ ] Đọc/ghi checkpoint `{last_day, pos, key}` mỗi instrument
- [ ] Khoá = hash df **tính đến ngày cuối** (không phải toàn df — nếu không, append hôm nay
      tự vô hiệu hoá checkpoint mỗi ngày)
- [ ] Không khớp → replay đầy đủ. Checkpoint là **tối ưu hoá thuần tuý**: hỏng thì chậm, không sai
- [ ] Cắt df từ ngày cuối (lead-in) + `resume_after_day` loại nó khỏi replay

⚠️ Hình thức triển khai ĐẦU TIÊN là **chạy song song** (tính cả hai đường, đối chiếu) →
`run_live_day` **chậm hơn** 5.5→8-10 phút, mỗi 3 slot bỏ 2. Chưa có lợi ích tốc độ nào cho
tới khi quan sát sạch rồi mới tắt đường cũ. Đừng deploy sát giờ phiên.

#### Đối chiếu song song: phiên đêm NKD bị bỏ sót (2026-08-10) — ĐÃ SỬA
Cờ bật đối chiếu là `--shadow-verify`, và scheduler chỉ truyền nó ở slot cuối ngày
(`_verify = ((_h, _m) == _LAST_SLOT)` → 15:55 ET). 22 slot đêm gọi
`_live_day_body(sid, clusters="nkd", prev_preflight=True)` — `verify` để mặc định `False`.

Log 08-03→08-10 có **đúng 6 dòng đối chiếu, 6 KHỚP, 0 LỆCH**, tất cả trong ngày 08-07;
MNKD có mặt 2 dòng. Mọi slot đêm chỉ in kết quả resume, không có gì đứng cạnh để so.

MNKD *có* được so ở 15:55 ET, nhưng đó là **khung khác**: slot đêm chạy `--clusters nkd`
và ghép bar live qua `_splice_nkd_live`, và chính slot đêm mới đặt lệnh NKD.
`verify_resume` phủ MNKD 14/14 offline → resume ở tầng engine đã chắc; cái chưa kiểm
hẹp hơn: resume trên **khung đêm đã splice bar live**.

Sửa: slot NKD cuối (02:55 ET) truyền `verify=True`, đúng lập luận đã viết cho slot cuối
ngày — cửa sổ vào lệnh NKD đã đóng nên 5 phút replay không cướp fill nào.
`global_index/test_scheduler_shadow_verify.py` 6 test; sv1/sv2/sv3 đã **chứng minh đỏ**
trên code cũ trước khi khôi phục bản sửa. Test đọc **câu lệnh dựng ra**, không đọc source
text — lỗi nằm ở đường nối giữa `add_job` và câu lệnh, đúng chỗ mà kiểm source sẽ đọc lướt qua.
Không đụng `runner.py`/engine → không kích hoạt gate reconcile (L12).

### Bước 6 ⏳ Bộ reconcile sau Bước 4
deploy_sim $42,459/1.72 · smoke diff $0.00 · 4 reconcile · pytest 208 · injection 14 · refreeze 68
(Ba lần chạy sau Bước 1/2/3 đều cho **cùng một bộ số**, không chỉ "pass".)
`test_ro6` fail — đã chứng minh có sẵn ở HEAD bằng cách stash rồi chạy lại.

### Trạng thái production HIỆN TẠI
**Runner vẫn nạp kiểu cũ.** Grep `resume_pos|resume_after_day|datr=` trong `global_index/`
và `futures/swing_tf.py` → rỗng. Ba commit chỉ MỞ CỬA trên engine, không ai bước qua.
Đó là lý do dừng ở bất kỳ bước nào cũng an toàn.

### Tồn đọng khác (độc lập)
- [ ] `maxhold_exit` 09:31 ET không chạy nếu scheduler bật muộn — lỡ 2 ngày liên tiếp
      (08-05 bật 09:43, 08-06 bật 10:35). Chưa tốn tiền vì vị thế mới hold 1d.
      **Hạn chót thật: thứ Hai 2026-08-10** (vị thế 08-05 + 5 ngày). Cần catch-up khi khởi động.
- [ ] G2 HARD lặp mỗi lần chạy, hệ thống vẫn giao dịch — guard vô hiệu trên thực tế
- [ ] `futures/swing_tf_harness.py` + bản copy ở root vẫn còn lỗi khoá `id(df)`

---

## Sub-task: maxhold_exit catch-up (2026-08-07) — DONE `91dbc0e`
Status: DONE

### Lỗi
APScheduler tính lần bắn KẾ TIẾP lúc khởi động. Bật lúc 09:43 thì mốc 09:31 hôm đó
**không trễ — nó không tồn tại**. Không misfire, không lỗi, không log gì.
Đã xảy ra 2 ngày liên tiếp: 08-05 (bật 09:43), 08-06 (bật 10:35).

Không tốn tiền chỉ vì chưa vị thế nào đủ 5 ngày. Ba vị thế vào 08-05 → mốc **thứ Hai 08-10**.

### Vì sao quan trọng hơn vẻ ngoài
MAX_HOLD = 15% số lệnh, tb **+$398.60**; CHANDELIER = 79.5%, tb **−$48.84**.
**Toàn bộ lợi nhuận thoát qua đúng job này.** Backtest thoát tại bar 09:30 ET
(INVARIANTS, bản sửa đã đổi baseline $41,266→$40,919). Lỡ slot → thoát qua
`run_live_day` ~14:10, **muộn hơn quy ước 4h40**.

### Sửa
`_catch_up_maxhold()` khi khởi động: ngày trong tuần + đã qua 09:31 ET + chưa ghi nhận
→ chạy ngay. State `global_index/maxhold_state.json` keyed theo ngày (khuôn `_preflight_ok`).
An toàn vì `run_maxhold_exit` idempotent và **không cần parquet tươi**.

### ⚠️ Lỗi tự tạo rồi tự bắt — dry-run ghi nhận như chạy thật
`_run` trả `True` khi `--dry-run` mà **không thực thi gì** → bản đầu ghi
`{"2026-08-07": true}` → scheduler thật sau đó sẽ **bỏ qua catch-up**.
Một buổi diễn tập vô hiệu hoá đúng cái nó diễn tập, âm thầm, ngay trước thứ Hai.
Tìm ra bằng cách **kiểm file state sau khi chạy thử**, không phải bằng đọc lại code.
Fix: `if ok and not dry_run`. Có test riêng cho ca này.

### Verify
`test_maxhold_catchup.py` 13 ca. Tách 2 tầng: quyết-định-có-gọi (job giả) vs
ghi-nhận (**closure thật**) — với job giả thì "failure không được ghi" pass vì
*không có gì ghi cả*. Phủ: biên 09:31, cuối tuần, ngày cũ, file hỏng (đọc = chưa chạy,
hướng an toàn), thiếu job id (không được làm sập scheduler).
pytest **241 passed**.

### Chạy thật 2026-08-07 10:41 ET — PASS
`[MAXHOLD] CATCH-UP` → `completed OK` → giữ nguyên MYM (hold=2d < 5), state ghi đúng.

---

## Sub-task: Rollover 2026-09-11 — 5 việc, CHƯA LÀM
Status: TODO — hạn 11/9

### Bối cảnh
Append từ IBKR bắt đầu **06/7**. Hai lần roll năm nay (13/3, 12/6) đều **trước** đó.
→ **Đường ống hiện tại chưa từng đi qua một lần roll nào.** Lần đầu: 11/9.

### Spread đã đo (IBKR, 2026-08-07)
| inst | T9 | T12 | spread | % | so bug thang giá đã sửa |
|---|---|---|---|---|---|
| MES | 7,747.25 | 7,814.00 | **+66.75** | 0.86% | 5.4× |
| MNQ | 29,634.25 | 29,932.50 | **+298.25** | 1.01% | 3.4× |
| MYM | 53,999.00 | 54,399.00 | **+400.00** | 0.74% | 10.3× |
| M2K | 3,015.60 | 3,039.10 | **+23.50** | 0.78% | 2.6× |

Cùng dấu, cùng biên độ → chi phí nắm giữ, không phải nhiễu. Bug thang giá nhỏ hơn
đã gây vào **sai chiều M2K** hôm 04/8, thiệt hại ~$1,532.

### Tầng dữ liệu — offset bị khoá vĩnh viễn
```python
if name not in splice_offsets:   # tính 1 lần
else:                            # dùng lại mãi
```
`ContFuture` = **ratio back-adjust về hợp đồng hiện tại**; roll → hợp đồng tham chiếu
đổi → bar mới trên thang mới, offset vẫn là hằng số cũ. Ta chỉ append, không fetch lại
lịch sử → **bậc nhảy ~67 điểm ghép thẳng vào chuỗi MES**.

**EMA KHÔNG bị ảnh hưởng** — nó tính trong 1 ngày trên bar 5 phút (`bars5 = b5[day]`,
:344-348), mà roll rơi vào ranh giới phiên. Thứ trúng đòn là **`datr` (ATR ngày)**:
vắt qua ngày, Wilder → nhiễm **~56 phiên** → dải chandelier nới rộng gần 3 tháng.
Với vị thế mở: `extreme` nhảy theo → **stop ratchet lên mức chưa từng có thật**.

**Chữa:** offset là back-adjustment **tích luỹ**, cộng `(close_cũ − open_mới)` mỗi lần
roll. `_apply_splice_offset` đã làm đúng phép tính, chỉ đang bị khoá. Diff (Panama)
là quy ước đúng vì engine tính hoàn toàn **theo điểm**.

### Tầng bảo vệ — NGUY HIỂM NHẤT
Nhánh thành công: *"position continues unchanged"*. **Không có `cancel_order` hay
`place_stop` nào** trong cả `_handle_rollover` lẫn `_handle_rollover_if_needed`.

1. Vị thế sang MESZ6 **không có stop**
2. Lệnh SELL STP trên MESU6 **vẫn treo**
3. Nếu chạm → khớp → **mở vị thế SHORT ma** trên hợp đồng sắp hết hạn
4. `pos.stop_price` vẫn trên thang cũ, lệch đúng bằng spread

**Không guard nào bắt được:**
- B3 so vị thế file vs broker → sau roll đều có MES ×1 → khớp
- B4 kiểm `stop_order_id is None or p.inst not in _working`; `stop_order_id` **không None**,
  còn `has_working_stop` khớp theo **`t.contract.symbol`** = `"MES"`, **không phân biệt
  tháng** → lệnh mồ côi MESU6 làm guard tin rằng MESZ6 được bảo vệ

> Guard so **mã instrument** trong khi rủi ro nằm ở **tháng hợp đồng**.

### 5 việc
- [ ] 1. Guard bậc nhảy tại điểm nối → `exit(1)`, fail-closed, người xác nhận
      (**dừng thay vì tự sửa**: roll 4 lần/năm; đổi 4 ngày giao dịch lấy việc không bao
      giờ âm thầm nắn lỗi dữ liệu thành chuỗi đẹp)
- [ ] 2. Neo lại offset tại roll (cộng dồn)
- [ ] 3. Huỷ STP hợp đồng cũ ngay sau khi CLOSE khớp
- [ ] 4. Quy đổi mức stop sang thang mới, đặt STP mới, cập nhật `pos`
- [ ] 5. **`has_working_stop` so cả tháng hợp đồng** ← sửa *cái mù*, 1-4 chỉ sửa *sự cố*

### Ranh giới hiểu biết
- **Đọc từ code, chắc chắn:** offset bị khoá; không huỷ/đặt lại stop; `has_working_stop`
  so theo symbol; B3/B4 không bắt được
- **Đo được:** spread 0.74–1.01%
- **Suy đoán, CHƯA quan sát:** bar append sau roll nhảy đúng bằng spread. Không kiểm được
  bằng dữ liệu quá khứ — lịch sử `ContFuture` đã được IBKR chỉnh liền mạch; bậc nhảy chỉ
  sinh từ *cách ta append*, nên chỉ lộ khi có roll thật giữa hai lần append
- **Chưa trả lời được:** `ContFuture` roll theo lịch riêng IBKR (theo khối lượng), **có thể
  không trùng** `ROLL_SCHEDULE` → vài ngày dữ liệu ở hợp đồng này, vị thế ở hợp đồng kia.
  Đây là lý do việc 1 phải phát hiện **theo bậc nhảy giá**, không theo ngày trong lịch
- **Chưa đo:** chi phí thật của việc thoát MAX_HOLD muộn 4h40

### test_ro6 — đã sửa (`3127a57`)
Lỗi ở **test**, không phải code: `ENTRY_DAY=06-10`, `ROLL_DAY=06-12` → hold=2 < 5 nên
`run_maxhold_exit` **đúng khi không đóng**, còn test khẳng định đã đóng. Sửa: tiêm vị thế
đủ già + `assert closed` để **tiền đề tự kiểm chính nó**. 18/18.

---

## 🚨 Sự cố: bậc thang offset trong parquet (2026-08-05 → 08-07) — ĐÃ SỬA `3953dba`
Status: DONE

### Chuyện gì xảy ra
Repair 04/8 ghi lại đuôi parquet ở **thang thô IBKR** (log: *"no offset applied"*, join
gap 0.003–0.043%), nhưng sidecar **giữ nguyên offset cũ**. Từ lần append 05/8,
`update_ibkr_daily` lại cộng offset đó vào mọi bar mới.

→ **Bậc thang trong cả 5 chuỗi giá tại 2026-08-05**, bằng đúng offset lưu:

| inst | bậc thang | điểm chuyển (UTC) |
|---|---|---|
| MES | +11.50 | 05/8 06:13 |
| MNQ | +183.00 | 05/8 06:14 |
| MYM | −57.00 | 05/8 06:17 |
| M2K | +7.20 | 05/8 06:20 |
| MNKD | +1065.00 | 05/8 06:50 |

Trước điểm chuyển: ~10,150 bar/mã khớp IBKR **median 0.0000, IQR 0.0000**.

### Bằng chứng — đối chiếu giá THẬT, không phải chuỗi IBKR khác
- **Lệnh khớp thật**: M2K BOT @ **3020.10** lúc 07/8 11:20:20 UTC. Parquet bar đó ghi
  O=3026.90 H=3027.30 L=3026.90 C=3027.00 → **giá khớp nằm NGOÀI High-Low**
- **ContFuture == hợp đồng thật**: M2KU6 vs ContFuture khớp 0.0000 trên 2,760 bar
- **parquet vs hợp đồng thật**: median +7.2000 trên 2,568 bar

Sau sửa: bar đó đọc O=3019.70 **H=3020.10** L=3019.70 C=3019.80 — giá khớp = High.

### Ảnh hưởng đo được — nhỏ hơn kích thước gợi ý
| | MES | MNQ |
|---|---|---|
| ATR ngày | 0.00 | **−6.93** (1.0%) |
| Dải chandelier | 0.00 | **−17.32 điểm** |
| Vị thế mong muốn | không đổi | không đổi |

**Giá lệnh chưa bao giờ sai** — `_splice_live` đo chênh parquet↔live rồi `to_candidate`
trừ ra. Xác nhận sau khi sửa: offset live tụt từ 10.75/184.75/−54.00/8.00/1065.00
xuống **−1.25/0.75/1.00/0.40/5.00** (cỡ 1 tick).

### ⚠️ Vì sao sống được 3 ngày
**Cơ chế bù trừ hoạt động tốt sẽ CHE lỗi ở tầng dưới nó.** Giá lệnh luôn đúng nên mọi
chỉ dấu vận hành bình thường. Không guard nào bắt:
- `assert_utc_convention` → kiểm nhãn giờ
- History invariant → kiểm bar cũ không bị ghi đè; ở đây bar cũ **không** bị đụng
- Join check → so 2 bar đều nằm **sau** bậc thang

### Sửa: `global_index/fix_offset_step.py`
Đo bậc thang bằng median trên vùng chồng lấn, trừ khỏi bar từ điểm chuyển, **đặt sidecar
về 0** (repair đã căn về thang thô). Backup: `_backup_20260807_195345_pre_offset_fix`.

Nghiệm thu: cả 5 mã median **0.0000**, IQR **0.0000** trên ~13,600 bar, kể cả vùng 05/8.

### Hai chỗ tôi đã nói SAI trong quá trình
- **"ATR Wilder → nhiễm ~56 phiên"** — SAI. `daily_atr_series` là `tr.rolling(14).mean()`,
  trung bình trượt **đơn giản 14 ngày**, nhiễm 14 phiên rồi rơi hẳn. Đã viết câu sai này
  vào nhiều comment/commit.
- **Lần đo ảnh hưởng đầu** cắt tại 00:00 ngày 05/8 trong khi điểm chuyển ở **giữa phiên**
  → báo "không ảnh hưởng" cho MNQ, sai.

---

## Sub-task: Rollover 2026-09-11 — 6 việc, ĐÃ XONG
Status: DONE (code) — **chưa chạy qua roll thật**

| # | việc | commit |
|---|---|---|
| 1 | Guard bậc nhảy giá (bar hỏng) | `fbe7abf` |
| 1b | **Phát hiện roll bằng ĐỊNH DANH hợp đồng** | `26581d8` |
| 2 | **Kiểm căn chỉnh hằng ngày** parquet ↔ IBKR | `5fd8b6d` |
| 2b | Roll được gọi đúng tên, không đổ cho sidecar | `e5cdba6` |
| 2c | **Tự neo lại khi đủ 4 điều kiện** + runbook | `25443d2` |
| 3 | Huỷ STP hợp đồng cũ khi roll | `b955e64` |
| 4 | Đặt STP mới, dịch theo spread **đã khớp thật** | `b955e64` |
| 5 | B5 so cả **tháng hợp đồng**, không chỉ mã | `b955e64` |

### Vì sao không dùng bậc nhảy giá để phát hiện roll
**Biến động 1 phút lớn nhất trong năm LỚN HƠN spread roll ở cả 4 mã** (MES 118.50 vs
66.75). Tách được hai loại không phải bằng **độ lớn** mà bằng **độ hiếm** — nhưng cửa sổ
ngưỡng chỉ 0.348–0.370%, quá hẹp. `qualifyContracts` trả `localSymbol` (`MESU6`) nên
phát hiện **chính xác tuyệt đối**, không cần ngưỡng.

→ Bậc nhảy giá đổi vai: từ **bộ dò roll** thành **lưới bắt dữ liệu hỏng**.

### Điều kiện tự neo lại (thiếu 1 trong 4 → từ chối)
1. Định danh hợp đồng đã đổi · 2. ≥500 bar chồng lấn · 3. IQR ≤20% mức dịch ·
4. Mức dịch trong 0.20–2.00% giá (đo được: spread 0.74–1.01%)

**Lưới đỡ:** neo sai → kiểm căn chỉnh **hôm sau** chặn. Sai lầm sống 1 ngày, không phải
3 ngày như sự cố offset.

**Tính chất an toàn đáng chú ý:** sự cố 05/8 (+11.50 = 0.148% giá) **không bị tự neo lại
ngay cả khi gán nhầm hợp đồng** — quá nhỏ so với carry. Nhưng M2K (+7.20 = 0.239%) thì
lọt qua cổng độ lớn; **chỉ điều kiện định danh chặn được nó** → đó là lý do điều kiện 1
là bắt buộc chứ không phải tham khảo.

### Đã bỏ có chủ ý
Kiểm chéo "các mã cùng dịch một chiều" — cần 2 lượt qua vòng lặp, trong khi điều kiện
3+4 đã phủ đúng kiểu hỏng đó. Log in đủ 5 mã để người đọc tự thấy.

### CHƯA kiểm chứng
Không thứ gì chạy qua roll thật. Lần đầu **11/9/2026** — runbook ghi rõ nên có người
theo dõi log 13:45–14:05 ET hôm đó.

---

## Sub-task: Checkpoint tự vô hiệu mỗi ngày (2026-08-07) — ĐÃ SỬA
Status: DONE

### Triệu chứng
Phiên 08-07 chạy `--shadow-resume` cả phiên nhưng **thu về gần như số 0**: bốn mã Rổ 4
báo `khong co checkpoint dung duoc` ở **mọi slot**. Chỉ MNKD chạy và có `DOI CHIEU KHOP`.
Không có ERROR nào — guard từ chối đúng thiết kế, nên nhìn qua tưởng bình thường.

### Nguyên nhân
Nhánh đẩy checkpoint chọn ngày theo **khung đã ghép** (parquet + bar live IBKR) — khung
này đã đủ ngày hôm qua nên neo vào hôm qua. Nhưng fingerprint băm trên **parquet**, mà
parquet chưa đủ: append chạy 13:45 ET nên ngày mới nhất luôn dừng giữa chừng, và **lần
append hôm sau mới điền nốt 13:46→23:59 ET của ngày đã bị neo**. Lịch sử "tính đến
`last_day`" tiếp tục lớn lên → fingerprint tự hỏng sau đúng một ngày, mãi mãi.

Đo được **554 bar** chênh trên MES/MNQ (553 MYM, 552 M2K) = đúng số bar 13:46→23:59 ET
ngày 08-06, và **khớp chính xác con số trong log phiên**. Phụ: `nay == log-phiên` tuyệt
đối → `fix_offset_step` chỉ đổi giá, không đổi số dòng.

### Vì sao MNKD sống sót — cho điều kiện tổng quát
| | ngày đóng lúc | so mốc append 13:45 ET | |
|---|---|---|---|
| Rổ 4 (khung ET) | 00:00 ET | **sau** | còn bị điền tiếp → hỏng |
| MNKD (khung Tokyo) | 00:00 JST = 15:00 UTC | **trước** | đã cố định → an toàn |

**Điều kiện: mốc cắt phải nằm trước ranh giới append.** Lấy session áp chót *trên chính
khung của dữ liệu* thoả cả hai mà không phải phân biệt mã nào.

### Đã làm
- [x] `replay_checkpoint.advance_day()` — tách thành hàm, đọc session **từ parquet**, lùi
      một ngày so với session cuối. Khung ghép không còn tham gia vào quyết định.
- [x] `run_live_day.py` gọi hàm đó thay logic inline
- [x] `test_advance_day.py` — 11 ca, gồm ca chốt thẳng tính chất: bar do append hôm sau
      thêm vào **không được** đụng lịch sử tính đến ngày đã chọn; và ca Tokyo giải thích
      MNKD
- [x] Bootstrap lại cả 5 mã. Kiểm: `usable=True` toàn bộ, mốc cắt đều đóng trên đĩa
      (MES/MNQ/MYM/M2K `last_day=2026-08-06`; MNKD `2026-08-07`)
- [x] OPERATIONS.md — cơ chế + quy tắc "ghi lại parquet thì phải `--bootstrap` lại"

### Bẫy đã mắc HAI lần trong một buổi (ghi để khỏi lặp)
Hai loader trả **hai khung khác nhau**: `futures._validated_core.load_parquet` → **ET
tz-aware**; `global_index.update_ibkr_daily._load_parquet` → **UTC**. Đếm bar bằng loader
này rồi so với fingerprint sinh bởi loader kia ra số vô nghĩa — lần đầu ra "chênh 477, dư
166 không giải thích được" (MNKD), lần sau ra "314" thay vì 554 (Rổ 4). **Cách bắt: tìm
mốc cắt cho ra ĐÚNG số dòng đã lưu, thay vì tìm cách giải thích phần chênh.**

### Files touched
global_index/replay_checkpoint.py, global_index/run_live_day.py,
global_index/test_advance_day.py, docs/futures/OPERATIONS.md, SCRATCHPAD.md

---

## Sub-task: STP đặt ngay lúc khớp — live chạy sai luật (2026-08-08)
Status: ĐÃ ĐO XONG, CHỜ QUYẾT ĐỊNH ĐIỂM VẬN HÀNH

### Phát hiện
`place_stop` đưa STP lên sàn **0–1 giây** sau khi khớp. `backtest_swing_tf` chỉ xét stop
**từ ngày hôm sau** (khối thoát chạy trước khối vào lệnh trong cùng vòng lặp ngày). Live
đang thực thi một luật thoát **chưa từng được kiểm định**, chặt hơn hẳn bản đã validate.

### Đo (model_sameday_stop.py — cổng đối chiếu trade-for-trade với engine, 4/4 mã KHỚP)
| kích hoạt STP sau | lệnh | P&L | thắng | lỗ tạm sâu nhất khi trần (tv/p95/max) |
|---|---|---|---|---|
| **0h (live hiện tại)** | 3.736 | **−$10.832** | 11% | — |
| 1h | 3.307 | +$19.906 | 13% | $31/$160/$1.351 |
| 2h | 3.141 | +$20.816 | 14% | $39/$208/$1.351 |
| 4h | 3.114 | +$34.112 | 15% | $41/$224/$1.372 |
| **8h** | 3.047 | **+$46.767** | 16% | $48/$271/$1.890 |
| sang ngày (= backtest) | 3.044 | +$47.166 | 16% | 0 |

Đường cong **tăng đều rồi bão hoà** → chỗ thở là cơ chế thật, không phải hiệu ứng nhóm
bar theo ngày lịch. 8h lấy **99,2%** edge. Stop vận hành hẹp bằng **1/22** dải chandelier
danh nghĩa ở cả 4 mã.

### Kết luận
KHÔNG cần sửa engine, KHÔNG cần chạy lại WFO. Cần **hoãn đặt STP**.

### Phải sửa hai chỗ, không phải một
1. `runner.py` — bỏ `place_stop` ngay sau OPEN fill
2. **`runner.py` guard B4** — nó tự đặt lại stop cho mọi vị thế `stop_order_id is None` ở
   MỖI lần chạy. Chỉ sửa (1) thì độ trễ còn ~5 phút, vẫn nằm ở cột tệ nhất. B4 phải biết
   cửa sổ trần là **có chủ đích**, chỉ báo động khi thiếu stop SAU cửa sổ.

### Chờ quyết định
Điểm vận hành chọn theo **rủi ro qua đêm chấp nhận được**, KHÔNG theo đỉnh P&L (chọn theo
đỉnh là curve fitting). Slot đêm 01:10 ET đã có sẵn — cách lệnh vào 14:00–15:55 ET hơn 9
tiếng, nằm sau điểm bão hoà.

  **Độ trễ vào lệnh là thứ yếu — hoãn STP mới là tất cả** (model_entry_latency.py, cùng
  cổng đối chiếu, 4/4 KHỚP). Độ trễ tính từ lúc bar 5 phút ĐÓNG (đo thật trên MES 08-07:
  bar 14:55–14:59, lệnh gửi 15:10:41 → trễ ~10,7 phút, giá tệ hơn 12 điểm):

  | kích hoạt STP | trễ 0p | trễ 5p | trễ 10p | trễ 15p |
  |---|---|---|---|---|
  | STP ngay (0h) | −$10.832 | −$9.358 | −$6.467 | −$7.044 |
  | STP sau 8h | +$46.767 | +$43.788 | +$43.868 | +$42.822 |
  | STP sang ngày | +$47.166 | +$44.183 | +$44.232 | +$43.060 |

  - Hoãn STP đáng **~$53k**; cắt độ trễ 15→0 phút đáng **~$4,1k**. Tỉ lệ **13:1**.
  - Hoãn STP **một mình là đủ**: dương ở MỌI mức trễ, kể cả 15 phút (= cadence hiện tại).
  - Bật resume một mình **vô ích**: dòng "STP ngay" âm ở cả bốn ô.
  - 8h ≈ sang ngày (99,2–99,4%) ở mọi mức trễ → điểm bão hoà vững, không phụ thuộc độ trễ.
  - Trễ 10p nhỉnh hơn trễ 5p (~$50–100 trên $44k) là **nhiễu**, đừng đọc thành xu hướng.

  **MNKD đo riêng — cùng mẫu, và mốc bão hoà KHÔNG suy ra được từ Rổ 4**
  (model_sameday_stop_nkd.py, cổng đối chiếu 865=865 KHỚP; ema=10, đồng hồ JST, nhãn
  SPY trễ 1 ngày):

  | kích hoạt STP | lệnh | P&L | thắng | stop-D0 |
  |---|---|---|---|---|
  | 0h (live cũ) | 1352 | **−$10.854** | 6% | 1143 (**85%** số lệnh) |
  | 1h | 1097 | −$2.719 | 7% | 883 |
  | 4h | 925 | +$10.478 | 11% | 651 |
  | 8h | 892 | +$19.082 | 13% | 530 |
  | sang ngày | 865 | **+$22.294** | 15% | 0 |

  ⚠ **8h chỉ đạt 86% edge của MNKD**, trong khi Rổ 4 đạt 99,2%. Nếu chọn điểm vận hành
  8h theo số của Rổ 4 thì mất 14% edge MNKD. Chọn "sang ngày" đúng cho cả hai sleeve —
  và đây là lý do phải đo từng sleeve chứ không suy ra.

- **STRESS_MID chưa được nối vào live — và có 2 lỗi tiềm ẩn cùng họ với lỗi STP.**
  `run_live_day.py:488` truyền `stress_bars_1015={}` cứng, scheduler không có slot
  ~10:15 ET → nhánh vào lệnh stress không bao giờ chạy. Không có vị thế thì không có stop.

  Khi bật lên sẽ vướng hai chỗ, **đều là live chạy khác backtest**:
  1. `to_candidate` chỉ giữ `entry` + `stop`, **vứt bỏ `target`** (2R) mà
     `stress_mid.entry_signal` trả về → không có lệnh chốt lời nào được đặt.
  2. `_mark_held_unchanged` được gọi cho swing và NKD, **không bao giờ cho stress** →
     khoá `(inst, "roska4_stress")` không nằm trong `desired`, nên
     `diff_desired_vs_held` đưa nó vào `exits` ở **mọi lần chạy kế tiếp**. Backtest giữ
     10:15→14:00; live sẽ đóng ở slot ngay sau, tức vài phút.

  **Hai điều tôi từng nói sai và đã đính chính:** (a) "stress vào-ra trong cùng run_day
  nên không tới được khối STP" — SAI, candidate stress không có trường `exit` nên
  `decide_day` GIỮ nó lại (`if newp.exit_day == day` là False); test STP3 pass chỉ vì
  tín hiệu giả trong test tự đặt `exit=DAY1`. (b) Lý do thật là **sleeve chưa được nối**.

### Chưa đo
- Độ trễ vào lệnh chưa nằm trong bảng (làm mọi cột xấu đi)
- $1.890 là lỗ *tạm thời* sâu nhất quan sát được 6 năm (có COVID 2020), không phải chặn trên

### Files added
measure_sameday_stop.py, model_sameday_stop.py

---

## Sub-task: STRESS_MID — NỐI VÀ THEO DÕI (2026-08-08)
Status: QUYẾT ĐỊNH ĐÃ CHỐT — nối, chưa thực thi (cần cron 10:20 ET)

### Quyết định
**Nối vào và theo dõi.** p=0,112 nghĩa là **chưa đủ bằng chứng**, KHÔNG phải đã chứng minh
không có edge — ước lượng điểm vẫn dương (474 lệnh, thắng 49%), và sleeve phủ khoảng giữa
phiên trong chế độ Stress mà không sleeve nào khác chạm tới. Paper là chỗ để theo dõi thứ
chưa chắc, rủi ro bằng không.

(Bản ghi trước đó của tôi ghi "KHÔNG NỐI" — đó là kết luận của tôi, đã bị bác. Giữ lại ghi
chú này để không ai đọc nhầm lịch sử.)

### Nối code hiện tại ≈ 91% luật đã kiểm định
`model_stress_exits.py` (cổng đối chiếu adapter từng lệnh, 4/4 KHỚP), giả định **một slot
sáng 10:20 ET, không có slot xen giữa**:

| | P&L | % |
|---|---|---|
| A — luật đã kiểm định (stop/target/14:00) | +$14.151 | 100% |
| **D — live thật: vào trễ 10p, thoát ~14:10, mất target** | **+$12.850** | **91%** |
| C — nếu có slot xen giữa buổi sáng (5 phút) | −$450 | 0% |

Ba nguồn lệch: mất `target` 2R (−5%), giá vào trễ ~10 phút (−15%), thoát ~14:10 thay vì
14:00 (**+$1.520**, tình cờ có lợi trong mẫu này — không phải thiết kế, đừng dựa vào).

### BẤT BIẾN BẮT BUỘC khi dựng cron
**Không được có slot nào gọi `run_live_day` giữa 10:20 và 14:05 ET.** Job 09:31
(`run_maxhold_exit`) và 13:45 (pre-flight) không gọi `generate_today_signals` nên an toàn.
Thêm bất kỳ slot nào xen giữa → `diff_desired_vs_held` đóng vị thế stress ngay lần chạy kế
tiếp → sleeve tụt từ +$12.850 xuống **−$450**, im lặng, không guard nào kêu.
`_mark_held_unchanged` KHÔNG gọi cho cluster stress — và **không được** thêm vào như một
bản vá, vì khi đó không gì đóng vị thế nữa và nó qua đêm.

### Việc phải làm khi thực thi — ĐÃ XONG 2026-08-09
- [x] `run_live_day --stress-entry`: dựng `stress_bars_1015` từ bar live, cắt tại 10:15,
      resample 5 phút. **Mặc định TẮT** — slot chiều chạy sau 4 tiếng, bật ngầm sẽ vào
      lệnh bằng tín hiệu cũ ở giá đã trôi
- [x] Cron **10:20 ET** `stress_mid`, `--clusters stress --stress-entry`,
      `prev_preflight=True` (job 13:45 chưa chạy lúc đó — cùng cơ chế slot đêm NKD)
- [x] Bất biến ghi vào `OPERATIONS.md` **và** chốt bằng test
      `test_stress_slot_invariant.py` (quét toàn bộ 49 job của scheduler)
- [ ] (tuỳ chọn, +5%) `to_candidate` giữ `target` và đặt lệnh chốt lời

### Kỳ vọng về "theo dõi"
474 lệnh / 8 năm / 4 mã ≈ **59 lệnh/năm toàn rổ**, chỉ trong chế độ Stress — dồn cục vào
2018, 2020, 2021, 2022. **Một năm êm có thể không có lệnh nào.** Đây là chuyện nhiều năm,
không phải nhiều tháng; đừng kỳ vọng vài phiên paper trả lời được câu hỏi edge. Và khi so
kết quả paper với backtest, nhớ hai bên đang chạy hai luật khác nhau (91%).

### Files added
model_stress_exits.py, model_ratchet.py

---

## Sub-task: Khoảng ân hạn cho stop — GIẢ THUYẾT ĐÃ QUA 4 CỬA, KHÔNG ÁP DỤNG (2026-08-09)
Status: ĐO XONG — ghi hồ sơ, KHÔNG đổi code

### Câu hỏi
Stop hoãn tới khi qua ngày vào lệnh; nhưng "qua ngày rồi thì đặt lúc mấy giờ" không nằm
trong luật nào — nó là hệ quả phụ của job nào dựng `FuturesRunner` trước (hiện: slot đêm
NKD 01:10 ET). Hoãn lâu hơn thì sao?

### Kết quả (Rổ 4, `model_activation_sweep.py`, cổng đối chiếu từng lệnh)
| kích hoạt sau | P&L | MaxDD | lỗ tạm khi trần (tv/p95/max) | >2× | năm thắng |
|---|---|---|---|---|---|
| 1,17h **(hiện tại)** | +$49.895 | $8.234 | $35/$259/$1.981 | 31% | 6/9 |
| 9,52h | +$93.375 | $7.144 | $62/$370/$1.563 | 28% | 9/9 |
| **16h** | **+$128.863** | $5.082 | $90/$561/$1.714 | 29% | 9/9 |
| 36h | +$128.028 | $5.317 | $120/$708/$2.806 | 28% | 9/9 |
| 72h | +$93.063 | $9.260 | $189/$1.013/$4.252 | 27% | 9/9 |
| không bao giờ | **−$46.369** | $60.138 | $228/$1.200/$4.252 | 27% | 2/9 |

MNKD cùng mẫu, đỉnh quanh 24–36h (+$34k–38k).

### Bốn cửa — qua hết
1. **Quét nhiều mốc**: vùng cao **rộng** 16–72h, không phải đỉnh nhọn
2. **Tách năm**: 9/9 từ mốc 9,52h
3. **IS / VAULT (OOS) / POST**: dương cả ba, cùng tăng theo độ trễ
4. **Đối chứng cô lập — quan trọng nhất**: nới ĐỘ RỘNG stop (giữ nguyên sizing) cư xử
   **ngược chiều**, đơn điệu xấu đi ở cả hai sleeve:

   | ×độ rộng | Rổ 4 | MNKD |
   |---|---|---|
   | 1,0× | +$49.895 | +$25.791 |
   | 2,0× | +$20.706 | +$16.380 |
   | 6,0× | −$40.377 | +$13.794 |

   → **Giả thuyết "hoãn = cách thô để nới stop" BỊ BÁC BỎ.** Cơ chế là *khoảng ân hạn*:
   stop hẹp là ĐÚNG (giữ lỗ nhỏ), nó chỉ không nên được vũ trang ngay sau khi vào lệnh.
   Nới stop phá hỏng chính cái làm nó tốt.

### VÌ SAO VẪN KHÔNG ÁP DỤNG
Bốn kênh rủi ro, **hai chưa đo được**:

1. Phơi nhiễm trực tiếp — **đã đo**, p95 $561 ở 16h, chấp nhận được
2. **Đuôi không bị chặn** — không stop thì lỗ chỉ bị chặn bởi MAX_HOLD 5 ngày. $4.252 là
   xấu nhất *quan sát được* 6 năm, không phải chặn trên. Chuỗi limit-move không có trong mẫu
3. **Breaker mù** — `_book_realised`: *"Realised only, no mark-to-market"*. Trần DD 15% và
   phanh −4%/ngày đọc equity **đã thực hiện**, nên lỗ tạm đóng góp **số 0**. Thay đổi này
   kéo thời gian phanh mù từ ~1 ngày lên **~3 ngày**. Đó là lý do "MaxDD giảm $8.234 →
   $5.082" gây hiểu nhầm: rủi ro chuyển từ *đã thực hiện* sang *chưa thực hiện* — đẹp lên
   vì đi vào chỗ không đo
4. **Phơi nhiễm đồng thời toàn danh mục — CHƯA ĐO, lỗ hổng lớn nhất**. MAE đo *theo từng
   lệnh*, nhưng Rổ 4 là 4 hợp đồng chỉ số Mỹ tương quan cao: một cú sốc vĩ mô đánh cả bốn
   cùng lúc, cả bốn đang trần. Phơi nhiễm đồng thời có thể gần 4×$561 và tương quan, không
   bù trừ. Thêm margin IBKR tính trên lỗ chưa thực hiện → margin call / thanh lý cưỡng bức,
   hệ thống không mô hình hoá ở đâu cả

### Nếu sau này làm tiếp — tối thiểu
- [ ] Đo phơi nhiễm **đồng thời toàn danh mục**, không phải per-trade
- [ ] Sửa breaker để nhìn cả lỗ chưa thực hiện, nếu không là **tháo phanh đổi lấy P&L backtest**
- [ ] WFO với luật mới; vault test hiện tại không còn mô tả hệ thống nếu đổi giờ kích hoạt
- [ ] Bề mặt nhiễu **±$25k** trong vùng cao → không chọn được một giá trị cụ thể

### Files added
model_activation_sweep.py, model_stop_activation_gap.py, model_gap_robustness.py,
global_index/test_stop_placement_time.py

---

# 🎯 KHỞI ĐIỂM CHO SESSION MỚI — monitoring & scaling (ghi 2026-08-11)

Hai chủ đề, bàn trong session riêng. **Monitoring trước, scaling sau** — scaling nhân lên
mọi lỗ hổng quan sát đang có, và hôm 10/08 vừa chứng minh: một lệnh stop mồ côi sống nguyên
buổi với MỘT vị thế; với bốn sleeve thì vừa vô hình gấp bốn vừa khó gỡ hơn.

**Chưa bàn khi hai mắt xích này chưa đóng** (đều trong vài tiếng, không phải vài ngày):
- 11/08 ~14:05 ET — B4 ĐẶT stop thật cho 3 vị thế Rổ 4 (lần đầu code stop mới chạm IBKR
  trên đường đặt lệnh, không phải chỉ đọc)
- Bài tập rollover MNQ — trình tự đóng-mở-huỷ-đặt chưa chạy thật lần nào

## A. Monitoring — hiện trạng

**Đã có (10/08):** báo cáo phiên tự chạy sau việc cuối trong ngày, phân biệt sự cố ĐÃ KẾT
THÚC với đang xảy ra, tiến độ chuyển resume; quét sửa stop mỗi ~2h; `_run` không còn nuốt
CRITICAL của tiến trình con thoát mã 0; pytest hết ghi vào log production.

**Ba mặt hiển thị, chưa có ranh giới rõ:**
| | trả lời câu gì | ai làm |
|---|---|---|
| dashboard (`live_state_data.js`) | P&L, đường bao rủi ro, trạng thái tiến trình | người khác |
| báo cáo phiên (`session_report.py`) | hôm nay xảy ra gì, cần làm gì | phiên 10/08 |
| (thiếu) | **NGAY BÂY GIỜ có gì hỏng không** | chưa ai |

**RÀNG BUỘC CỨNG cho toàn bộ việc monitoring: KHÔNG đụng engine.**
Mọi thứ làm ra chỉ được **quan sát**, không được đổi hệ giao dịch hành xử ra sao.

CẤM sửa: `futures/**` · `global_index/runner.py` · `signal_layer.py` · `ibkr_broker.py` ·
`net_exposure_multi.py` · `run_live_day.py` · `run_maxhold_exit.py` · `run_scheduler.py`
(lịch job là hành vi hệ thống, không phải quan sát).

ĐƯỢC sửa: `session_report.py` · `dashboard.html` · `dash/**` · `monitor/**` · module mới
thuần đọc.

Ba hệ quả phải nhớ:
1. **Chỉ đọc, không ghi.** Không phát lệnh IBKR, không ghi `live_positions.json`, không ghi
   file trạng thái nào. Lưu ý `run_stop_repair.py` (làm 10/08) KHÔNG phải mẫu để noi theo —
   nó dựng `FuturesRunner` nên có GHI sổ; đó là công cụ vận hành, không phải giám sát.
2. **Thiếu dữ liệu thì BÁO CÁO, không tự thêm.** Nếu giám sát cần thứ engine chưa phát ra,
   ghi lại thành một mục để quyết riêng — đừng sửa engine để lấy nó.
3. Nối IBKR chỉ để ĐỌC thì được (`get_positions`, `get_working_stops`,
   `unprotected_positions`), và phải dùng clientId riêng, không trùng 1/2/3.

**Câu hỏi còn mở:**
- Báo cáo là **kéo, không phải đẩy**. Hỏng lúc 20:00 thì sáng mới biết. Ngưỡng nào đáng
  đánh thức người? (paper thì chấp nhận được, tiền thật thì không)
- Chưa có khái niệm **"đã biết, đang hoãn"** → G2 HARD sẽ hiện như sự cố mới mỗi sáng
- Bảng `_KNOWN` phải nuôi: lỗi mới rơi vào khoảng trống thì không được diễn giải

**Dữ liệu dashboard đang có — dùng làm căn cứ, đừng bàn chay:**
`runner_health{last_heartbeat, ibkr_connected}` · `meta{account, hard_dd_pct .15,
target_dd_pct .10, daily_loss_pct .04, n_contracts 1, final_equity, net_pnl, system_epoch,
broker_equity, paper_start, max_dd_dollars, max_dd_pct, total_days, clusters, breaker_events,
backtest_calmar, operational_status{runner.alive,pid,last_run_day}, events}` ·
`snapshots[]{date, equity, decision{realized_today,entries,exits}, per_cluster_pnl,
regime_attribution, cluster_stats, holding_distribution, running_metrics}`

## B. Scaling — bốn trục, mỗi trục một chặn cứng khác nhau

Chặn cứng chung phát hiện 10/08: engine ngầm giả định **một vị thế mỗi mã**, và bốn tầng
riêng biệt dựa vào giả định đó mà không tầng nào khai ra.

| trục | chặn cứng |
|---|---|
| thêm hợp đồng mỗi vị thế | mọi số `deploy_sim` đo ở **1 micro** → phải đo lại ở cỡ đích; sizing/DD/breaker đổi theo |
| thêm sleeve dùng chung mã | **bù trừ ròng** — đã chốt hướng subaccount riêng, CHƯA triển khai |
| thêm mã mới | dữ liệu, sizing, ngân sách `MultiClusterGuard` |
| pyramiding | **ĐÃ BÁC** (L16) — không mở lại |

Lưu ý về con số: `broker_equity` ~$996k (tài khoản paper) vs `final_equity` $50k (nền hệ
thống). Hai thang khác nhau, và đã gây một lỗi thật (B1 loại peak_equity ghi theo số dư
broker). Mọi bàn luận scaling phải nói rõ đang dùng thang nào.

---

# ✅ KẾT PHIÊN THỨ HAI 2026-08-10 — tổng kết

**Phiên chạy tốt.** Mở 3 vị thế Rổ 4 (MYM SHORT @53.969 · MES SHORT @7.773 · M2K LONG
@3.025,3), cả ba hoãn stop ĐÚNG luật, vũ trang **14:00 ET thứ Ba**. MNKD đóng trong ngày —
đúng thiết kế, slot 14:05–15:55 giữ NKD hoạt động để lệnh thoát chạy được ban ngày.

**Mốc 15:55 ĐẠT: `DOI CHIEU KHOP` đủ 5 mã** → tiến độ resume **2/5**.

**3 lượt quét sửa stop chạy thật** (12:20 · 16:20 · 18:20 ET), đều `completed OK`, không lần
nào kèm `thoat OK nhung da ghi`. Đường code mới nhất — và là đường duy nhất ngoài slot giao
dịch ghi vào `live_positions.json` — đã có bằng chứng thật.

**Sự cố tìm ra và đã xử:** STP mồ côi #12 trên MYM (huỷ được, `code=202`), gốc là lỗi hệ
thống clientId — mọi lần MAX_HOLD đóng vị thế đều để lại lệnh mồ côi. Đã vá.

## ⚠️ SỬA LẠI một điều tôi nói sai trong phiên
Tôi ghi "thứ Ba 01:10 ET B4 đặt STP thật cho MNKD" — SAI. MNKD đã đóng hôm nay nên 01:10
không còn gì để vũ trang. Ba vị thế đang giữ đều là Rổ 4, vũ trang 14:00 ET. **Lần đầu B4
đặt stop thật bằng code mới là thứ Ba ~14:05 ET.**

## Còn lại chưa có bằng chứng thật (2 mắt xích cuối)
- [ ] **Thứ Ba ~14:05 ET** — B4 ĐẶT stop thật cho 3 vị thế Rổ 4. Lần đầu
      `has_working_stop` dạng mới + `get_working_stops` dạng danh sách chạm IBKR trên
      đường ĐẶT LỆNH, không phải chỉ đọc. Tìm 3 dòng `STP: placed ... orderId=`
- [ ] **Thứ Ba** — bài tập rollover MNQ (`exercise_rollover_live`). Scheduler TẮT, bật lại
      kèm `--shadow-resume` TRƯỚC 13:45 ET
- [x] **Full suite trên cây cuối (HEAD ca07d43): 477/477, 0 đỏ.** Hai test nhiều hơn lần
      475 là hai ca múi giờ thêm ở commit cuối.

---

# ⏰ THỨ HAI 2026-08-10 — ba việc, theo thứ tự giờ

## 09:31 ET — mốc MAX_HOLD đầu tiên mà catch-up phải đỡ — **XONG, có phát hiện**
> MYM đã đóng · `maxhold_state` ghi `2026-08-10: true` · catch-up kiểm rồi bỏ qua (đúng).
> NHƯNG `cancel_order('12')` thất bại IM LẶNG → STP mồ côi treo tới ~10:30 ET; phát hiện
> bằng cách hỏi thẳng IBKR (sổ/state/log đều sạch), huỷ được sau khi nối lại đúng clientId
> 81 (`code=202`). Gốc: `run_live_day` đặt bằng id 1 còn `run_maxhold_exit` huỷ bằng id 2 —
> **mọi lần MAX_HOLD đóng vị thế đều để lại STP mồ côi**. Đã vá (cả hai về id 1); vì mỗi job
> là subprocess nên bản vá CÓ HIỆU LỰC NGAY, không cần khởi động lại scheduler.

MYM SHORT vào **05/8** → thứ Hai tròn 5 ngày. Đây là lần đầu bản vá `91dbc0e` gặp
tình huống thật.

- Bật scheduler **trước 09:31 ET**, hoặc để catch-up tự chạy nếu bật muộn
- Kiểm log: `[MAXHOLD] CATCH-UP` (nếu bật muộn) hoặc job 09:31 chạy bình thường
- Xác nhận MYM đã đóng. Nếu chưa, chạy tay:
  `python -m global_index.run_maxhold_exit --positions-path live_positions.json --port 4002`

## ~10:00 ET — bài tập rollover thật (`abeec34`) — **HOÃN SANG THỨ BA 11/08**
> Chốt 10/08 lúc ~11:00 ET: hoãn để giảm số biến động trong một ngày đã thay đổi nhiều.
> Roll THẬT là 2026-09-11, còn một tháng — không gấp. Nhưng phải làm TRƯỚC ngày đó, và
> tốt nhất trước khi ba bản vá `_roll_stop` (ghi mức trước khi đặt · tôn trọng cửa sổ hoãn ·
> tách hàm) phải chạy thật lần đầu vào đúng ngày roll.
>
> Việc này đằng nào cũng đòi dừng scheduler, nên gộp luôn lần khởi động lại để nạp: 10 lượt
> quét (thay 19), listener báo cáo cuối ngày.
>
> Phạm vi nó KHÔNG phủ: script chạy một tiến trình một clientId (61), vừa đặt vừa huỷ trong
> cùng kết nối, nên không phát hiện được lỗi clientId chéo tiến trình. Với rollover thì không
> sao — C2 chạy trong `run_live_day`, cũng cùng clientId 1.

Mắt xích **duy nhất** của rollover chưa chạm IBKR thật: trình tự đóng-mở-huỷ-đặt.

```powershell
cd d:\raits
Get-Process pythonw,python | Where-Object { $_.CommandLine -like "*run_scheduler*" } | Stop-Process
python -m global_index.exercise_rollover_live            # kiem dieu kien
python -m global_index.exercise_rollover_live --apply    # chi khi buoc tren "checks passed"
pythonw -m global_index.run_scheduler --port 4002 --shadow-resume   # BAT LAI TRUOC 13:45 ET
```

Dùng **MNQ** (hệ thống không giữ mã này). Script tự từ chối nếu scheduler còn chạy,
thị trường đóng, hoặc MNQ đã có vị thế/lệnh. Dọn dẹp trong `finally`.

**Ba câu nó trả lời:** vị thế có sang hợp đồng mới không · **stop cũ có bị huỷ không**
(nếu không → có thể khớp và **mở vị thế ma**) · hợp đồng mới có stop không.

## 15:55 ET — dòng đối chiếu shadow đầu tiên
Slot cuối chạy `--shadow-verify`. Tìm trong `live_day_0810.log`:
```
[shadow] MES: DOI CHIEU KHOP — day du == resume
```
`DOI CHIEU LECH` = **CRITICAL**, dừng kế hoạch chuyển sang resume.

⚠️ Nhớ bật scheduler với `--shadow-resume`, không có cờ thì không thu được gì.

⚠️ Phiên 08-07 chỉ MNKD có dòng đối chiếu (xem sub-task checkpoint ở trên). Thứ Hai
**phải thấy đủ 5 mã**. Nếu vẫn còn `khong co checkpoint dung duoc` thì bản sửa chưa ăn —
điều tra trước khi kết luận gì về resume.

---

## Tồn đọng khác (không gấp)
- [ ] `G2 HARD` báo mỗi lần chạy, hệ thống vẫn giao dịch — guard vô hiệu trên thực tế
- [ ] `run_scheduler.py` gắn FileHandler vào root logger lúc import → output pytest lẫn
      vào log scheduler production
- [ ] Chuyển đường giao dịch sang resume — **đây mới là lúc có lợi ích tốc độ**
      (run_day 5m03 → dưới 1 phút, hết bỏ slot).
      Điều kiện: **5 phiên LIÊN TIẾP đủ 5 mã KHỚP, không mã nào LỆCH**. Ngưỡng 5 là phán
      đoán chứ không phải kết quả đo — đổi bằng `--resume-streak`.
      **Tiến độ hiện tại: 1/5** (07/08 đủ 5 mã). `session_report` có mục riêng theo dõi,
      tự đếm từ log mọi ngày, nên không phải nhớ.
      Lưu ý: một phiên **thiếu mã** không tính là đạt — 07/08 slot 15:55 chỉ sinh dòng cho
      MNKD; bốn mã kia không phải "khớp ngầm" mà là chưa được hỏi. Một mã LỆCH đưa chuỗi
      **về 0**, không phải trừ một.
- [ ] `futures/swing_tf_harness.py` + bản copy ở root vẫn còn lỗi khoá `id(df)`
- [ ] Đo chi phí thật của việc thoát MAX_HOLD muộn 4h40 (đã xếp ưu tiên mà chưa đo)

---
## Sub-task: STRESS_MID cron TẮT — stop khoá theo MÃ thay vì theo VỊ THẾ (2026-08-10)
Status: BLOCKED (đã tắt cron, chờ sửa tầng theo dõi)

### Completed
- [x] Tắt cron `stress_mid` 10:20 ET (`run_scheduler.py`, khối `if False` + chú thích lý do)
- [x] `test_stress_slot_invariant.py` đảo chiều: khẳng định cron ĐANG TẮT, giữ bất biến
      10:20–14:05 cho lúc bật lại (5 test pass)
- [x] Truy hết tầng: B3 `file_key` **có cộng dồn** (đúng, cùng chiều OK); `has_working_stop`,
      `get_working_stops`, `unprotected_positions` đều khoá theo **mã**, không theo vị thế
- [x] `cancel_order(p.stop_order_id)`, rollover, `exit_keys` — theo vị thế, KHÔNG hỏng
- [x] Ghi `docs/futures/OPERATIONS.md` mục "STRESS_MID: tại sao cron 10:20 bị TẮT" + SCRATCHPAD

### Hai lỗi đã ghi nhận
1. **Bù trừ ròng.** `get_positions()`/`ib.positions()` trả vị thế ròng có dấu. Swing LONG +
   stress SHORT cùng mã → net 0 → B3 MISMATCH → halt entry, và `unprotected_positions()`
   bỏ qua cả hai (`if not p.position: continue`) nên phép kiểm bảo vệ không thấy chúng.
   `held_stress` chỉ chặn vị thế STRESS thứ hai, không chặn vị thế SWING cùng mã.
2. **Stop không phân biệt được vị thế.** Cùng chiều thì không bù trừ, nhưng
   `has_working_stop(inst)` khoá theo symbol → B4 từ chối đặt stop cho vị thế thứ hai; và
   `unprotected_positions()` kiểm `if exp in have` (sự tồn tại, không phải số lượng) nên
   báo an toàn. Một hợp đồng trần vĩnh viễn, không guard nào kêu.

3. **`repair_stops.py` ghi id sai vào sổ.** `by_inst = {p["inst"]: p}` (dòng 150) — một vị
   thế đè cái kia; `p["stop_order_id"] = new_ids[p["inst"]]` (dòng 113–114) — đóng cùng một
   order id lên mọi vị thế của mã đó. Nặng hơn hai lỗi trên: nó làm hỏng DỮ LIỆU mà tầng
   đang chạy đúng (`cancel_order(p.stop_order_id)`) dựa vào — đóng vị thế A sẽ huỷ stop của
   vị thế B.

### Đã sửa (2026-08-10) — câu hỏi "có stop cho MÃ này" → "VỊ THẾ này có được phủ"
- [x] `check_open_orders.classify`: mỗi STP được **một** vị thế nhận (bỏ `matching[0]`);
      thêm `Stop` NamedTuple mang `qty`; thêm verdict `PARTIAL` (phủ thiếu, KHÔNG tự vá);
      stop thừa đúng chiều giờ hiện ra là HAZARD; stop của vị thế ngược chiều cùng mã
      KHÔNG còn bị báo HAZARD nhầm
- [x] `repair_stops`: bỏ hẳn `by_inst`; `classify` trả luôn vị thế nó xét; `_key` =
      `(inst, cluster)`; `id_corrections` + `_write_positions` ghi id theo từng vị thế
- [x] `unprotected_positions`: cộng **số hợp đồng** theo `(mã, expiry, bên)` rồi so với vị
      thế — thay cho `if exp in have`; và giờ mới xét BÊN (trước đây SELL stop được tính là
      bảo vệ cho SHORT)
- [x] `has_working_stop(inst, direction=None, contracts=None)` — dạng cũ giữ nguyên nghĩa,
      dạng mới đếm độ phủ đúng bên; B4 gọi dạng mới
- [x] `get_working_stops` → `{inst: [orderId,…]}` (trước đây ghi đè, nhớ mỗi một id);
      B4 + B5 hỏi *"id vị thế này ghi nhận còn sống không"* thay vì `p.inst in working`
- [x] `PROTECTIVE_SIDE` chuyển về `ibkr_broker` làm nguồn duy nhất, CLI import lại
- [x] B5: chỉ tắt cảnh báo khi **mọi** vị thế trên mã đó đang hoãn (trước: một vị thế hoãn
      làm câm cảnh báo cho vị thế khác cùng mã đã thật sự mất stop)
- [x] B4: tách `STP ID DRIFT` (WARNING, đã được phủ nhưng id trong sổ trỏ vào lệnh chết)
      khỏi `B4 NAKED` (CRITICAL) — phép kiểm cũ im lặng ở ca này, còn phép kiểm mới nếu
      không tách sẽ hô NAKED vào vị thế đang được bảo vệ, mỗi slot một lần
- [x] Test: `test_stop_per_position.py` (13 mới), `test_unprotected_positions.py` (+5 ca
      bên/độ phủ), `test_stp.py`/`test_stp_accept.py`/`test_deferred_verdict.py` cập nhật

### 🔴 SỰ CỐ ĐANG MỞ (2026-08-10): STP mồ côi #12 trên MYM
Status: CẦN NGƯỜI XỬ LÝ

- MAX_HOLD 09:31 đóng MYM xong nhưng `cancel_order('12')` THẤT BẠI. Xác nhận bằng truy vấn
  IBKR: `get_working_stops()` → `{'MYM': ['12']}`, `get_positions()` → chỉ MNKD.
- BUY STP treo ~54708.68 không có vị thế phía sau → chạm giá sẽ MỞ một lệnh LONG.
- Cảnh báo runner đã kêu nhưng `_run` nuốt vì `returncode == 0`. ĐÃ VÁ (`_run` giờ ghi ra
  dòng CRITICAL/ERROR kể cả khi thoát 0; `test_run_echoes_critical.py`, 6 test).
- [x] **ĐÃ HUỶ #12** bằng `repair_stops --client-id 81 --execute` → `code=202 Order Canceled`
- [x] **NGUYÊN NHÂN GỐC — lỗi hệ thống**: IBKR chỉ nhận huỷ từ clientId đã đặt lệnh, nhưng
      `run_live_day` đặt bằng id 1 còn `run_maxhold_exit` huỷ bằng id 2 và `repair_stops`
      bằng 86 ⇒ **mọi lần MAX_HOLD đóng vị thế đều để lại STP mồ côi** (15% số lệnh), và cả
      đường huỷ của `repair_stops` chưa bao giờ chạy được. Đã đưa maxhold + stop_repair về
      id 1; `repair_stops` in ra lệnh chạy lại kèm id chủ. `test_stop_client_id.py` (5)
- [x] `repair_stops` VERIFY không còn đếm DEFERRED là gap
- [ ] (cũ) HUỶ #12: dừng scheduler → `python -X utf8 global_index/repair_stops.py` (xem báo
      cáo ORPHAN) → thêm `--execute` → khởi động lại scheduler (lần khởi động này cũng làm
      cron STRESS_MID tắt thật và nạp 19 slot quét-sửa)

### Khung thời gian đặt stop — ĐÃ XÁC NHẬN LÀ CHỦ ĐÍCH (2026-08-10)
- [x] Ghi `docs/futures/OPERATIONS.md` mục "Khung thời gian đặt lệnh — CÓ CHỦ ĐÍCH":
      cả Rổ 4 và NKD đều vũ trang stop 14h sau khi sang ngày mới, đo trên đồng hồ phiên của
      chính sleeve (14:05 ET / 01:10 ET); khai bằng múi giờ nên DST không làm trôi
- [x] Giải thích vì sao B4 không lọc cluster là ĐÚNG: nó gộp hai việc — vũ trang lần đầu
      (theo sleeve, `_stop_deferred` quyết định) và sửa chữa vị thế mất stop (không theo
      sleeve). Lọc theo cluster giết vế hai; bỏ `_stop_deferred` giết vế một
- [x] XÁC NHẬN bằng vị từ thật trên đúng lịch slot — và câu hỏi ban đầu chỉ đúng MỘT NỬA:
      vị thế MỚI thì 01:10 chỉ NKD / 14:05 chỉ Rổ 4; vị thế CŨ thì slot nào cũng chạm cả hai
      (đường sửa chữa). `B4 REPLACED` lúc 1h sáng cho Rổ 4 = guard làm việc, không phải rò
- [x] `test_slot_arms_which_sleeve.py` (8 mới, kèm ca DST) + memory `project_stop_arm_design`

### Lượt soi lại stop (2026-08-10) — 3 lỗ hổng nữa, ở rollover
- [x] C2 ghi mức stop chỉ khi lệnh được nhận → bị từ chối thì mức hợp đồng CŨ ở lại sổ, B4
      đặt mức đó lên thang giá hợp đồng MỚI phiên sau. Sửa: ghi mức TRƯỚC khi đặt
- [x] C2 vũ trang stop sớm — đặt ngay bất kể cửa sổ hoãn. Roll không dời `entry_day` nên
      cửa sổ không đổi. Sửa: C2 tôn trọng `_stop_deferred`
- [x] `classify` có thể nhận nhầm stop của hợp đồng đã chết khi C2 huỷ hụt (hai STP cùng
      chiều khác expiry). Sửa: nhận `stop_order_id` mình ghi TRƯỚC, và chỉ khi đúng chiều
- [x] Tách `_roll_stop` khỏi `_handle_rollover` để test gọi được code thật — bản test đầu
      chép lại logic vào helper rồi assert lên nó
- [x] `test_stop_rollover_gaps.py` (9 mới); `test_rollover_stop.py` (9 cũ) vẫn xanh
- [x] VÁ `has_working_stop` mù expiry: B4 hỏi thêm `unprotected_positions()`, bất đồng thì
      bên khớp `(mã, expiry, bên)` thắng; `None` thì KHÔNG ghi đè (test_b4_8/9/10)
- [x] VÁ khoảng trống sửa chữa: `run_stop_repair.py` + 19 slot ở ba lỗ (15:55→01:10 9h15,
      02:55→09:31 6h36, 09:31→14:05 4h34). signal_fn rỗng, không gọi run_day/run_maxhold_exit;
      `_stop_deferred` vẫn chặn nên không vũ trang sớm. `test_stop_repair_slots.py` (9)
- [x] BẰNG CHỨNG THẬT ĐẦU TIÊN: `run_stop_repair --dry-run` (chỉ đọc) chạy
      `unprotected_positions()` bản mới trên IBKR thật → "TRẦN: MNKD x+1 hợp đồng 20260910
      (phủ 0)" đúng như cửa sổ hoãn quy định; MYM vắng mặt ⇒ stop #12 phủ đúng hợp đồng/bên/số


### RÚT LẠI — luật một-vị-thế-mỗi-mã (không khớp thiết kế)
Tôi đã siết `signal_layer` + `verify_runner_real` thành "một vị thế mỗi mã trên mọi cluster"
để chặn bù trừ ròng, rồi **hoàn nguyên cả hai**. `deploy_sim.py:180-218` chạy
`StressMidEngine().backtest_basket()` ĐỘC LẬP với swing rồi nối hai danh sách lệnh — sim đã
kiểm định CHO PHÉP stress nằm cùng mã với swing. Siết luật đó = live chạy luật backtest chưa
kiểm (đúng hình dạng đã mất $53k ở chuyện stop), và phá `verify_runner_real.py` vốn có nhiệm
vụ "reproduces deploy_sim fit_C trade-for-trade".

### Next steps — bù trừ ròng CHƯA GIẢI, là điều kiện tiên quyết bật cron
**ĐÃ CHỌN (2026-08-10): (1) subaccount riêng.** Đường duy nhất không đụng tới con số đã
kiểm định — hai đường kia đều đòi đo lại. Chưa triển khai.
- [x] **(1) Subaccount riêng cho stress** — CHỌN — bù trừ ròng biến mất vì hai sleeve không chung
      sổ ở IBKR. KHÔNG đụng chiến lược, KHÔNG cần đo lại. Giá: thêm việc vận hành + một
      kết nối nữa
- [~] (2) Nhận luật một-vị-thế-mỗi-mã rồi ĐO LẠI — BỎ `deploy_sim --include-stress` với ràng
      buộc đó. Giá: Rổ 4 giữ vị thế phần lớn số ngày (4 mã mở đồng thời 45–47%) nên nhiều
      khả năng phần lớn lệnh stress bị cắt — +$12.850 sẽ khác hẳn, có thể không còn đáng bật
- [~] (3) Cho stress dùng mã khác — BỎ (ES/NQ full-size hoặc ngoài Rổ 4) — hết chồng lấn.
      Giá: phải đo lại + đổi bậc rủi ro
- [ ] Triển khai subaccount: mở subaccount IBKR, quyết cách runner định tuyến order theo
      cluster (account field trên order? hay tiến trình riêng + clientId riêng?), tách
      `live_positions.json` hay giữ chung một sổ
- [ ] Sau khi subaccount chạy: bật cron + sửa `test_the_stress_slot_is_disabled`

### Key decisions
- Tắt cron chứ không vá vội trước thứ Hai: cả ba tầng đều fail theo hướng "báo an toàn",
  nên vá một chỗ mà sót chỗ khác thì tệ hơn là không bật
- Giữ cờ `--stress-entry` của `run_live_day` để chạy tay khi kiểm thử — chạy tay có người
  nhìn, cron thì không
- Bảng giờ ET: dòng "STRESS thoát 14:00" là SAI — 14:00 là trần. Đo được stop 35% ·
  target 20% · eod 45%, tức 55% thoát sớm hơn. Live thoát ở slot 14:05 (~14:10)

### Files touched
global_index/run_scheduler.py, global_index/test_stress_slot_invariant.py,
docs/futures/OPERATIONS.md, SCRATCHPAD.md

---
## Sub-task: Sửa comparator paper_vs_backtest — nhãn regime dừng ở 2024-12-31 (2026-08-11)
Status: IN PROGRESS (chờ gate Calmar)

### Vấn đề
Panel `paper_vs_backtest` trả `null` suốt 12 ngày. Nguyên nhân bề mặt là curve cũ
(2026-07-30) — nhưng chạy lại KHÔNG đủ, vì comparator hỏng ở tầng dữ liệu:

`generate_replay_snapshots.py` dùng `spy_daily.csv`, dừng ở **2024-12-31**. Hai cluster
tra nhãn theo hai kiểu khác nhau:
- swing/stress: `labels.get(day)` (dict thuần) → `None` sau 2024-12-31 → gate ở
  `futures/_validated_core.py:402` chặn → **ngừng vào lệnh**
- global_nkd: `RegimeLabels.get` → `self.reg.asof(target)` (`global_index/regime.py:58`)
  → **nối giá trị cuối**, chạy tiếp tới 2026 trên nhãn ĐÓNG BĂNG ở 2024-12-31

Hệ quả: cả đoạn 2025-2026 của `backtest_curve.json` là NKD một mình, trong khi live giao
dịch cả Rổ 4 lẫn NKD. Panel so hai hệ khác nhau.

### Completed
- [x] Trace đủ chuỗi: `basket_labels` → `benchmark_daily` (đọc CSV thuần, không nối) →
      `label_regimes` → gate dòng 402; đối chiếu với `RegimeLabels.asof`
- [x] Xác nhận `spy_daily_live.csv` là tập cha đúng nghĩa: trùng khít 2012/2012 ngày chồng
      lấn (lệch max 0.0), thêm 402 ngày tới 2026-08-11
- [x] Đổi `generate_replay_snapshots.py:40` → `spy_daily_live.csv` + comment ghi cơ chế
- [x] Sinh lại curve; backup bản cũ ở `global_index/backtest_curve.spydaily.bak`
- [x] Gate 1 — không look-ahead: equity 2018-01-30 / 2022-12-30 / 2024-12-31 trùng khít
      (98,430.51 giữ nguyên). Đúng như dự đoán: `hmm_fit_end` cắt ở 2024-12-31 và
      `label_regimes` gán nhãn bằng cửa sổ mở rộng nên đoạn IS không thấy dữ liệu mới
- [x] Gate 2 — cả 3 cluster giao dịch tới 2026 (swing 2026-08-11, nkd 2026-08-12,
      stress 2026-04-01), không còn dừng ở 2025-01-02 / 2024-08-09

- [x] Gate 3 — degradation đo bằng ĐÚNG quy ước của floor (`deploy_sim`, frozen, 2-tick,
      `--end 2024-12-31`, no-stress). Cả hai lệnh tái lập chính xác số trong INVARIANTS:
      baseline $42,459 / Calmar 1.72 / MaxDD $3,574 · floor fit_A $42,565 / 1.65 / $3,744.
      `1.72 > 1.65` giữ nguyên → engine chưa trôi. `roska4_stress taken 0` ở cả hai xác nhận
      quy ước no-stress

- [x] Phương án 1 — khai rõ nhãn (đã làm 2026-08-11). `dashboard.html`: ô Calmar đổi nhãn
      phụ `IS 1.65` → `floor 1.65 · quy ước khác`, thêm `CALMAR_NOTE` làm tooltip cho cả ô
      giá trị lẫn nhãn phụ, ghi luôn "ngưỡng màu 2.0/1.0 là ngưỡng chung, KHÔNG phải floor".
      Panel degradation đổi nhãn thành "Backtest Calmar (floor fit_A — frozen, no-stress)" +
      "Paper Calmar (live, ít ngày)". `dash/analytics/`: `IS Baseline` → `Floor fit_A` +
      cùng tooltip. Đã `node --check` cả JS rời lẫn khối inline của dashboard.html

### Hoãn — làm khi tới phần dashboard cho paper trade
- [ ] **Quy ước Calmar: gỡ `floor` khỏi thanh metric, chỉ để nó cạnh `paper_calmar` trong
      panel degradation.** Đã chốt phương án C. Toàn bộ lý lẽ, bảng 7 ràng buộc, hai phương
      án đã loại, và cái giá phải chấp nhận (`paper_calmar` sẽ `N/A` một thời gian vì
      `system_epoch` = 2026-08-10) ghi ở **`monitor/DASHBOARD_PLAN.md` → mục "Calmar
      convention"**. Hiện mới chỉ vá bằng nhãn (phương án 1), chưa sửa cấu trúc.
      Ngưỡng màu 2.0/1.0 của thanh metric xem lại cùng lúc, đừng tách riêng

### Key decisions
- Comparator cũ hỏng theo HAI hướng cùng lúc, không phải một: thiếu Rổ 4 **và** phóng đại
  NKD. P&L NKD sau 2024-12-31 rơi $12,851 → $4,636 (2.8 lần) khi thay nhãn đóng băng bằng
  nhãn thật. Tổng curve mới THẤP hơn $3,138 dù đã cộng thêm swing +$4,992
- Hai đường cong khớp số học: 98,430.51 + (12,851.40 − 193.90) = 111,088.01 (cũ);
  98,430.51 + (4,635.85 + 4,992.01 − 108.76) = 107,949.61 (mới)
- `per_cluster_pnl` trong snapshot là LUỸ KẾ lặp lại mỗi ngày — cộng dồn ra $9.9M trên tài
  khoản $50k. Phải đo bằng biến thiên. Giá trị bất khả thi là thứ bắt được lát cắt sai
- Loại trừ giả thuyết stop: việc hoãn stop tới phiên sau là để KHỚP backtest
  (`runner.py:1907-1937`), không phải lệch khỏi nó. Backtest test stop TRƯỚC khối vào lệnh
  trong cùng vòng lặp ngày (`_validated_core.py:314` vs `:400`)

### Ghi nhận để quyết riêng (KHÔNG tự sửa — ràng buộc "không đụng engine")
- `run_scheduler.py` CẤM sửa: `G2 HARD` bắn 35/35 lần chạy mỗi ngày làm bão hoà kênh cảnh
  báo — một ERROR mới lạ sẽ chìm nghỉm. Cần quyết cách khử trùng lặp
- Re-freeze HMM (fit_end 2024-12-31, đã 20 tháng) là việc engine, cần mở ràng buộc
- Live gộp mọi exit thành `why="signal exit"`, không phân biệt CHANDELIER / MAX_HOLD như
  backtest có `reason` → không quy trách nhiệm phân kỳ được. Cần engine phát ra nhãn này
- `SLIPPAGE = 2.0` tick trong script vs đo được 28 / 8 / 7 / 6 tick trên 4 lệnh gần nhất
  (N=15, chưa đủ kết luận)

### Files touched
global_index/generate_replay_snapshots.py (dòng 40 + comment)

---
## Sub-task: session_report — mã thoát bị hiểu nhầm thành job hỏng (2026-08-11)
Status: DONE (còn 2 mục để quyết riêng)

### Vấn đề
Dashboard hiện SESSION_REPORT là **failed** mỗi ngày, dù báo cáo chạy xong và ghi file bình
thường. Chuỗi nhân quả:

- `session_report.main()` dùng mã thoát làm KÊNH PHÁN QUYẾT: `return 1 if need else 0`
- `run_scheduler._run()` (dùng chung cho mọi job) hiểu mã ≠ 0 theo nghĩa SỨC KHOẺ:
  `log.error("[%s] exited with code %d")`, rồi đổ tail stdout ra CŨNG ở mức ERROR — nên
  dòng "chi tiết lỗi" lại chính là câu `đã ghi bao_cao_0811.txt`
- `monitor/backend/job_journal_reader.py:99` bắt chuỗi `"exited with code"` → `failed`

Báo cáo sinh ra để TÌM việc nên `need=True` gần như mọi ngày — đo 05/08–11/08: **6/6 ngày**
`need=True`, exit=1. Đây là một dòng ERROR giả MỖI NGÀY, không phải sự cố lẻ.

### Completed
- [x] Bỏ mã thoát làm kênh phán quyết: `session_report.main()` luôn `return 0`, kèm comment
      ghi đủ chuỗi nhân quả. Từ đây mã ≠ 0 chỉ còn một nghĩa: script thật sự vỡ
- [x] Xác nhận KHÔNG mất thông tin: `monitor/backend/report_reader.read_report` gọi thẳng
      `collect_session_report` trong tiến trình và trả về cả `need` lẫn `issues` — dashboard
      đọc mức độ từ nội dung báo cáo, chưa từng cần mã thoát
- [x] Blocker (CHẶN) cũng KHÔNG đẩy mã thoát lên: "hệ thống đã dừng vào lệnh" mà báo bằng
      câu "exited with code 1" thì vẫn sai chữ. Mức độ thuộc về nội dung báo cáo
- [x] Kiểm: exit=0, nội dung giữ nguyên (mục "VIỆC CẦN LÀM" vẫn còn cả 2 việc).
      `test_session_report_slot` + `test_resume_progress` 28 pass, `test_dashboard_backend`
      19 pass

### Còn phải quyết
- [ ] **Lịch sử vẫn đỏ.** Các dòng `exited with code 1` của những ngày trước vẫn nằm trong
      log scheduler, nên dashboard vẫn hiện các lần chạy CŨ là failed. Không vá bằng cách
      cho `job_journal_reader` bỏ qua "exited with code" của SESSION_REPORT — làm vậy sẽ che
      luôn một lần vỡ THẬT sau này. Nếu muốn sạch thì phải giới hạn theo ngày cắt
- [x] **Luật `cancel_order` bắt nhầm dòng INFO — ĐÃ SỬA.** Khoá trần `"cancel_order"` khớp
      cả `cancel_order: cancelled orderId=N` (INFO, THÀNH CÔNG). Thay bằng hai khoá dạng
      thất bại: `"STILL OPEN 5s after cancelOrder"` (sai clientId) và
      `"cancel_order(orderId="` (exception, dấu ngoặc phân biệt với dạng hai chấm — và
      KHÔNG đụng dòng `STP ORPHAN: cancel_order(62) returned False` vì dòng đó không có
      chữ `orderId=` trong ngoặc).

      `"not found among open orders"` CỐ Ý bỏ ra ngoài. Nó có ba nguyên nhân mà dòng log
      không phân biệt được — lệnh đã xong / số hiệu là số ma / lệnh chưa từng được nhận —
      và cả ba đều làm `cancel_order` trả `False` → runner kêu CRITICAL `STP ORPHAN` ngay
      dòng sau, kèm đủ mã, cluster, orderId, việc cần làm. Bằng chứng live 06/08 12:10:29:
      hai dòng cách nhau 0 giây, orderId 62 là số ma còn stop thật #9 vẫn treo. Giữ lại chỉ
      là bản sao nghèo thông tin hơn của cùng một sự cố.

      Đo trước/sau trên 6 ngày: 07/08 70→28, 08/08 15→6, 10/08 55→22 (giữ nguyên toàn bộ
      dòng ERROR thật), 11/08 2→0 (hết báo nhầm). Sau khi sửa, `'Không huỷ được một lệnh ở
      sàn'` vẫn nổi ở 07/08 và 10/08; 06/08 chuyển đúng về `STP ORPHAN` thay vì đếm hai lần.

      **Đánh đổi đã biết:** ngày 05/08 giờ ra `need=False`. Hôm đó có hai dòng
      `"not found in OPEN TRADES"` (orderId 9, 10) mà KHÔNG kèm STP ORPHAN, vì chính sự cố
      05/08 mới sinh ra dòng CRITICAL đó. Cách viết cũ ấy đã tuyệt chủng trong code hiện
      tại, nên chạy báo cáo cho 05/08 sẽ không nêu hai lệnh mồ côi đó nữa. Với code HIỆN
      TẠI thì mọi `not found` đều kéo theo STP ORPHAN — không mất gì về sau
- [ ] Còn phải quyết: `cancel_order` trả `False` cho CẢ trường hợp lành (lệnh đã khớp/đã
      huỷ từ trước) nên runner kêu CRITICAL `STP ORPHAN` "vào TWS huỷ tay" cả khi không còn
      gì để huỷ. Sửa đúng là cho `cancel_order` phân biệt "không thấy vì đã xong" với
      "không thấy vì số ma" — nhưng nằm ở `ibkr_broker.py`/`runner.py`, thuộc diện CẤM
- [ ] `run_scheduler.py` (CẤM sửa) — hai lỗi phải để quyết riêng:
      (a) `_run` không phân biệt job dùng mã thoát làm phán quyết, và câu chữ
      "exited with code N" đọc như crash;
      (b) `subprocess.run(..., text=True)` thiếu `encoding="utf-8"` → giải mã bằng codec
      locale (cp1252) trong khi con ghi UTF-8, bóp méo TOÀN BỘ output bắt được của mọi job,
      kể cả các dòng CRITICAL/ERROR in lại ở dòng 370 — đúng thứ người ta bắt output để đọc.
      Hôm nay không lộ chỉ vì các dòng đó tình cờ toàn ASCII

### Files touched
global_index/session_report.py

---

## Sub-task: Realtime dashboard — audit + sửa (IN PROGRESS 2026-08-14)
Status: IN PROGRESS

### Completed
- [x] **Audit read-only** → `REALTIME_DASHBOARD_AUDIT.md`: 2 Critical, 4 High, 8 Medium, 7 Low.
      Verdict: trang an toàn ở chiều "không gây hại" (read-only tuyệt đối, 0 nút lệnh,
      client_id 99 tách khỏi runner 1) nhưng CHƯA tin được để kết luận "hệ thống đang ổn".
- [x] **Plan 12 task** → `docs/futures/REALTIME_DASHBOARD_FIX_PLAN.md` (TDD từng bước)
- [x] **T1** hai test tĩnh tự-suy-diễn chặn C1/C2 tái diễn (`monitor/test_realtime_contract.py`).
      Không allowlist thủ công: id tạo động qua innerHTML tự được chấp nhận.
      Về sau phải lọc comment cả-dòng trước khi grep — comment giải thích chính bug
      bị bắt như thể là code.
- [x] **T2** harness Playwright (`monitor/test_realtime_dom.py`): Flask cổng tạm, stub `/api/**`,
      static assets thật. Đã CHỨNG MINH stub thật sự chặn (equity 77777 / regime Stress
      render đúng, werkzeug log không thấy request `/api/*` lọt qua).
- [x] **T3 (C1)** gỡ incident IBKR-connectivity + broker-reconcile khỏi nhánh chết
      `if ($('schedulerHealth'))`; bỏ nén gap dựa trên cờ suy diễn `twsOutageOpen`,
      thay bằng kiểm tra incident CÓ THẬT trong mảng.
- [x] **T4 (C2 backend)** `schedule_status`: thêm freshness `stale` + `state_age_seconds`.
- [x] **T5 (C2 frontend)** bỏ `hidden` khỏi `runnerContext`, đưa tuổi snapshot lên header + rail.
- [x] **T6 (H1)** một sự thật duy nhất về "đã phục hồi chưa":
      backend `job_journal_reader` set `lifecycle_status`/`recovered_at` cho MỌI job
      failed|missed (trước chỉ nhánh missed+stop_repair); frontend Now Monitor đọc
      `open_incidents ?? incidents` (dùng `??` — `[]` là truthy nên `||` rơi về list đầy đủ).
- [x] **Ngoài plan — lane `recovered`**: 6 slot NKD mất trong đêm là sự thật về đêm đó.
      Bỏ khỏi lane báo động là đúng, để biến mất khỏi trang thì không. Now Monitor giờ có
      bucket thứ ba gộp theo stream: "6 NKD decision slots lost / 02:00–02:25 ET /
      recovered by NKD_NIGHT_0230", nhãn RECOVERED xanh, không tính vào incident count.
- [x] **T11 backend (M7)** `open_issue_reader.coverage` thêm `evidence_ends` + `stale_days`.
- [x] **T12 phần backend/khóa**: route `GET /favicon.ico` → 204; hai bất biến khóa trong
      `test_realtime_contract.py` (không write-surface; không render `breaker.dd_pct`).

### Completed (đợt 2 — 2026-08-14/15)
- [x] **T7 (H3/H4)** không bịa `14:05 ET`; sort journal theo epoch millis; `localTime` → `etDateTime`
- [x] **T8 (H2/M5)** `MIN_METRIC_DAYS = 20` — Sharpe hiện `--` kèm `n=5 trading day(s); needs 20`;
      HMM fit đổi màu theo `non_convergence_count` (`45/45 complete / 45 warn`, class `warning`)
- [x] **T11-frontend (M4 blocker + M8)** — trang thật hiện
      `Broker acct $996,440 / −$4,040 since Jul 8, 2026` ngay dưới `Paper Equity $50,229 / +$229`
- [x] **T9 (M1/M2/M6)** kiểm giá stop + hướng so với market_price; cộng dồn số lượng đa-cluster;
      `Protection` tách covered/deferred/naked → trang thật `1 covered`, không báo động giả
- [x] **T10 (M3)** `positionKey` = `inst|cluster|direction|entry_day`
- [x] **T12-frontend (L1/L3/L4)** xoá dead code rail + CSS mồ côi; gộp 39 dòng known-debt còn 1
      (`COMPLETED 13 · RECOVERED 6 · KNOWN DEBT 1`); Open Issues mở trên mobile
- [x] **L7 gỡ hoãn, đã đóng** — `is_clean_exit`/`is_debt_exit` dùng chung cho hai reader.
      Bẫy: nhánh debt phải kiểm TRƯỚC nhánh sạch vì `"thoat OK nhung"` chứa `"thoat OK"` làm
      tiền tố; đảo thứ tự sẽ xoá phân loại debt của 39 job. Dữ liệu thật không đổi phân loại nào.
- [x] **Contract test payload** (blocker #6 của audit) + **guard read-only cho cả 4 dashboard**
- [x] **Test bắt nội dung bị CẮT**, không chỉ trang bị cuộn — bản sửa C2 từng tạo ra một ca
      clipping (header 608px trên viewport 487px) mà test cũ vẫn xanh

### Next steps — AUDIT PHASE 2 (mở 2026-08-15)
Chi tiết: `REALTIME_DASHBOARD_AUDIT.md` mục "Audit Phase 2" ở cuối file.
Phase 1 toàn lỗi ĐÃ XÁC NHẬN. Phase 2 phần lớn là ĐƯỜNG DẪN CHƯA AI CHẠY — code có, nhánh có
viết, chưa test nào đi qua, chưa lần nào xảy ra thật. Có thể đúng sẵn; không ai biết.

Làm B trước A: nhóm B rẻ (stub + assert, không đổi code sản phẩm) và mỗi test biến một
"không biết" thành "ổn" hoặc "một finding thật". Chạy hết B rồi mới biết Phase 2 lớn cỡ nào.

**ĐÃ XONG 10/10 (2026-08-15).** Nhóm B trả lời đúng câu hỏi nó được dựng ra để hỏi:
**5/7 đường dẫn đã đúng sẵn**, chỉ thiếu test — không thiếu code. Nếu gộp chung vào danh sách
Phase 1 rồi gọi hết là "lỗi", ta đã báo 5 lỗi không tồn tại.

- [x] **P2-B1** `breaker.level` HALTED/SHUTDOWN — đúng sẵn; `test_a_tripped_circuit_breaker_is_never_reported_as_nominal`
- [x] **P2-B2** broker-only position — đúng sẵn; `test_a_position_the_runner_does_not_know_about_raises_an_incident`
- [x] **P2-B3** runner-only position — đúng sẵn; `test_a_position_only_the_runner_believes_in_raises_an_incident`
- [x] **P2-B4** `model_age URGENT` — đúng sẵn; `test_a_stale_model_is_shown_as_debt_without_crying_wolf`
- [x] **P2-A1** nửa sau của M8 — **đã sửa**: `runnerDead` ⇒ `meta={}` + `snapshot=null`, số hiện
      `--` thay vì giá trị cũ (`realtime.js:324-326`). M8 nay đóng đủ hai nửa
- [x] **P2-A2** — **RÚT LẠI, không phải finding.** Banner ghi "Monitor backend unavailable";
      một endpoint chết không phải backend chết, nên all-or-nothing đúng với thông điệp nó mang
- [x] **P2-B5** `regime_unreliable` — **LỖI THẬT**, đã sửa: `stripEntriesBlocked` + incident
      Now Monitor (`realtime.js:505/515/528/563`)
- [x] **P2-B6** `halted_today` + `rejected_detail` — đúng sẵn; `test_guard_blocked_and_cap_rejected_signals_are_listed`
- [x] **P2-B7** `refreeze pending` — **LỖI THẬT**, đã sửa: bucket thứ tư `debts`, nhãn KNOWN DEBT,
      không kéo rail vào báo động (`realtime.js:728-763`)
- [x] **P2-C1** 8/10 endpoint thiếu contract test — đã bổ sung

### L6 ĐÓNG — đổi tên xong, gate đã phân định (2026-08-15)

- [x] `dd_pct` → `dd_pct_display`, `day_dd_pct` → `day_dd_pct_display` ở cả 7 điểm
      `runner.py` (3 dump_state + 4 payload notify). CHỈ đổi tên khóa; giá trị số,
      công thức, mọi quyết định giao dịch không đổi.
- [x] **Lần rà đầu SÓT 2 consumer**, tìm ra khi làm gate — bài học: grep tên field là chưa đủ,
      phải grep cả tên **tiền tố** của nó:
      · `dashboard.html:2546-2550` đọc `ops.breaker.dd_pct` / `day_dd_pct` (consumer SỐNG,
        có `test_dashboard_live_snapshot.py` chạy `startLive()` của nó)
      · `test_operational_fixes.py:970` — nằm sau `if halt_events:` nên chưa từng chạy
      · thêm 2 chỗ `context: {dd_pct: …}` trong event tổng hợp của `dashboard.html`;
        `_logCtx` in tên khóa nguyên văn nên chúng nằm cùng log với event thật
- [x] Consumer đã cập nhật: `shared/live.js:176` (giữ `fmtPctAlready`), `dashboard.html`,
      `test_event_playback.py`, `test_operational_fixes.py`
- [x] **Test tôi viết bị RỖNG, đã sửa.** `assert "breaker.dd_pct" not in js` khớp luôn
      `dd_pct_display` vì tiền tố ⇒ khối `misused` bên dưới không bao giờ đỏ được. Tách thành
      `test_the_one_place_that_does_read_the_percent_unit_field_formats_it_as_percent`, canh
      `shared/live.js` — nơi THẬT SỰ đọc field. Chứng minh đỏ: lật `fmtPctAlready` → `fmtPct`.
- [x] **GATE: ĐỎ TỪ TRƯỚC, không phải hồi quy.** Chạy song song working tree và một
      `git worktree` tại HEAD, diff hai output: khác biệt duy nhất là **dòng nhãn của chính
      test** (`dd_pct` → `dd_pct_display`) và tên thư mục tạm. Cả 6 FAIL giống hệt ở HEAD.
      Dùng worktree chứ KHÔNG `git stash` như kế hoạch cũ ghi — `runner.py` lúc này còn chứa
      việc song song (`_append_trade` retry-exit + MAX_HOLD, `exit_reason`), stash sẽ cuốn theo.
- [x] **Chỉ stage 7 dòng rename của `runner.py`**, không cuốn việc song song: dựng blob từ
      `git show HEAD:global_index/runner.py` + thay chuỗi, `git hash-object -w --no-filters`,
      `git update-index --cacheinfo`. Working tree không bị đụng.

### Breaker HALT — hai test duy nhất canh nó đều RỖNG, đã sửa (2026-08-15)
Phát sinh từ gate L6. Không thuộc audit dashboard; đây là code giao dịch.

- [x] **Nguyên nhân**: P2a (`test_event_playback.py`), PART 3 cùng file, và T26
      (`test_operational_fixes.py`) đều dựng HALT bằng `MockBroker(account=$42.500)`. Nhưng
      runner **cố ý** đo drawdown trên equity hệ thống (`breaker.account` + P&L đã chốt), không
      phải số dư broker — `runner.py:751-765` ghi rõ lý do: tài khoản paper có ~$995k trong khi
      hệ thống size cho $50k, lấy số dư broker làm mẫu số khiến mọi ngưỡng bảo vệ xa gấp 20 lần.
      `state.equity` khởi tạo = `breaker.account` = $50.000 = đỉnh ⇒ DD 0,00% ⇒ level OK.
      **Hệ quả: không có test sống nào chứng minh circuit breaker HALT hoạt động.**
- [x] **Sửa**: đặt đỉnh đúng chỗ một drawdown thật để lại — $50.000 dưới đỉnh $60.000 = 16,67%,
      qua ngưỡng cứng 15%. Đây là ca restart-sau-chuỗi-thua, đúng hình dạng runner khôi phục từ
      state đã lưu (`runner.py:809`). KHÔNG đụng code giao dịch, chỉ sửa test.
- [x] **Thêm P2a.7** — mọi check cũ chỉ kiểm HALT được BÁO CÁO, không check nào kiểm nó CHẶN
      LỆNH. Lượt inject cho thấy vì sao cần: khi HALT hỏng, breaker rơi xuống **WARN, vốn vẫn
      cho vào lệnh** (`allow_new_entries` gồm cả WARN) ⇒ runner mở vị thế ở DD 16,67% trong khi
      dashboard chỉ hiện màu hổ phách "approaching limit".
- [x] **Chứng minh đỏ được**: chèn `if False` vào nhánh HALT của `futures/circuit_breaker.py:69`
      ⇒ P2a.2/.4/.5/.6/.7 và T26.1 đỏ; khôi phục ⇒ xanh. T26.2 chạy LẦN ĐẦU TIÊN.
- [x] **T13 cũng cùng khuyết tật, đã sửa** (`test_operational_fixes.py`): persist đỉnh $55.000
      rồi đưa runner2 một broker $46.750 và chờ HALT — equity hệ thống là $50.000 nên DD thật
      chỉ 9,09%. **T13.2 che lỗi**: nó tự tính DD bằng `halt_equity` truyền tay, báo 15,00%
      trong khi breaker đang nhìn 9,09% — một check xanh nằm ngay trên hai check đỏ mâu thuẫn
      với nó. Nay đo trên `runner2.state.equity`, đỉnh $60.000 ⇒ DD 16,67%, `halted=1`.
- [x] **Chứng minh đỏ bằng monkeypatch trong tiến trình**, KHÔNG sửa file trên đĩa. Lần đầu tôi
      chèn `if False` thẳng vào `futures/circuit_breaker.py` trong lúc suite của bạn đang chạy —
      sai, có thể gây failure ma trong lượt chạy đó. Cách đúng: patch
      `CircuitBreaker.status` runtime, vô hình với mọi tiến trình khác.
- [x] **Kết quả `test_operational_fixes.py`**: HEAD 118 passed / 5 failed / 123 total →
      nay **122 passed / 2 failed / 124 total**. Tăng 1 tổng vì T26.2 lần đầu chạy được.
- [x] **P1.8 cùng loại, đã sửa**: nó assert `snapshots[0]` là ngày CUỐI, tức mảng đảo ngược.
      Hợp đồng thật là tăng dần — production `live_state_data.js` chạy 08-10 → 08-14, và
      `test_dashboard_live_snapshot.py` ls1/ls3 khoá việc dashboard lấy phần tử CUỐI. Check sai
      nên đỏ mãi, khiến cả gate không đọc được. Nay assert cả hai đầu để bắt được đảo chiều.

### Dọn hết phần tồn đọng (2026-08-15, đợt 3)

**Chủ đề chung của cả đợt: test báo xanh mà không kiểm gì.** Sáu ca, ba hình dạng khác nhau.

- [x] **~195 check vô hình với pytest.** `check()` chỉ `print` + `append`, `sys.exit(1)` nằm
      trong `if __name__ == "__main__"`. Dưới pytest mọi hàm test in ra rồi return ⇒ luôn xanh.
      Đo: script 122 passed/2 failed vs pytest "31 passed"; và `test_event_playback` từng báo
      "11 passed in 2152s" — 36 phút không thể đỏ. Sửa: bọc từng hàm test.
      **Đã thử fixture autouse và BỎ**: assert sau `yield` là lỗi TEARDOWN, pytest in
      "31 passed, 2 errors" — con số passed gây hiểu nhầm đứng ngay cạnh lỗi.
- [x] **T5.2** — KHÔNG phải lỗi E1. `runner.py:142-146` cố ý miễn trừ khi PID trùng chính nó
      (`run_live_day` lấy lock rồi `__init__` lấy lại). Test tạo instance thứ hai *cùng tiến
      trình* nên rơi trúng miễn trừ ⇒ khẳng định ngược với thiết kế. Nay spawn tiến trình thật;
      thêm **T5.2b** ghim luôn miễn trừ để không ai "sửa" nó thành tự huỷ mỗi lần chạy.
- [x] **T7.4** — literal 9 khoá viết cứng, mâu thuẫn với T7.2 ngay hai dòng trên. Nay suy từ
      `dataclasses.fields(OpenPos)`. **Nó lập tức tìm ra `exit_reason` không được persist** —
      set ngày đánh dấu exit, đọc ngày exit chạy, có thể là tiến trình khác ⇒ restart giữa hai
      mốc ghi CLOSE không có exit path, đúng lỗ hổng field đó sinh ra để lấp. Đã thêm vào
      `_openpos_to_dict`/`_openpos_from_dict` (`.get()`, tương thích ngược). Thêm **T7.5**
      round-trip vì "có khoá" yếu hơn "giá trị quay về".
- [x] **snapshots không có trần** — `LIVE_SNAPSHOT_LIMIT = 500` (~2 năm giao dịch), cắt TRƯỚC
      vòng tính metrics. Payload phẳng ở 250 KB. Thêm PART 2i, và gate đã chạy ĐỎ trước khi sửa.
- [x] **`dump_state` chiếm 99,4% `run_day`** (profile: 4,07s/4,09s). `_running_metrics` gọi 501
      lần, 1,64s chỉ để dựng `pd.Timestamp` từng khoá (~700k lần). Vector hoá index:
      **4094 → 1436 ms**, metrics **bit-identical** (đã đối chiếu trên đường cong 1400 ngày và
      dict xáo trộn).
- [x] **`sys.exit()` cấp module làm sập collection.** `test_ibkr_injection.py` và
      `futures/test_refreeze.py` (tìm bằng quét AST, không phải vấp rồi mới sửa). pytest dính
      `SystemExit` lúc import ⇒ INTERNALERROR ⇒ **"no tests ran"**. Đây là lý do 7/8 "failure"
      trong lastfailed — chúng chưa từng hỏng. `pytest global_index/ futures/` trước: không chạy
      được; sau: **533 passed**.
- [x] **`test_incomplete_tail_is_not_extended`** — lỗi thật duy nhất trong 8 mục. Đặt cứng
      `runner_events_20260812.jsonl`, nhưng runner suy tên file từ ts của event ⇒ từ 13/08 emit
      rơi sang file khác, `assert path.read_bytes() == partial` xanh trên file không ai đụng.
      Nay suy tên động + assert emit không đi lạc chỗ khác.
- [x] **Danh sách gọi test trong `__main__` duy trì bằng tay** — thêm PART 2i mà quên khai báo,
      script vẫn in "69 passed, 0 failed / 69 total" trên một test nó không hề gọi. Nay tự phát
      hiện theo `co_firstlineno`.

Gate: `global_index/ + futures/` **533 passed** · `monitor/` **250 passed** ·
`test_operational_fixes` script **126/0/126** (HEAD: 118/5/123) · `test_event_playback` **ALL PASS**.

### CÒN LẠI — quyết định thiết kế, chưa làm
- [ ] Chi phí `dump_state` vẫn là O(500 × N) vì metrics "as at" mỗi ngày cần đường cong đầy đủ
      tới ngày đó. Chặn hẳn được nếu tính metrics trên cửa sổ đã cắt thay vì từ epoch — nhưng
      thế là ĐỔI Ý NGHĨA con số (Calmar từ đầu cửa sổ, không phải từ epoch), nên không tự làm.

### ⏰ CẦN LÀM — CÓ HẠN CHÓT
- [ ] **Restart scheduler trước 18:30 ET Chủ nhật 2026-08-16.** Sweep Chủ nhật
      (`stop_repair_sun_1830` trong `global_index/run_scheduler.py`, commit `83ac849`) đã ở
      trong code nhưng **chưa có hiệu lực** — APScheduler đọc cron lúc khởi động. Không restart
      kịp thì tuần này vẫn hở 6,5 tiếng giữa lúc thị trường mở lại và slot sửa stop đầu tiên.
      Đây là hạ tầng giao dịch nên Claude không tự restart.

### Còn mở từ Phase 1 — KHÔNG CÒN GÌ
- [x] **L6** đóng 2026-08-15 — xem mục riêng ở trên.
- [x] **M8** đóng đủ hai nửa: nửa đầu rail gọi tên nguồn, nửa sau qua P2-A1 (`runnerDead`).
      P2-A2 rút lại vì không phải finding.
- [x] **Backend đã restart, cả bốn thay đổi có hiệu lực** (đo trên cổng 5002):
      `/favicon.ico` → 204 · `state_age_seconds` = 27705.7 · `coverage.evidence_ends`
      = 2026-08-14 · `lifecycle_status` = 6 recovered. `freshness: not_expected_yet`
      với snapshot 7.7h tuổi là đúng: slot due gần nhất là LIVE_DAY_1555 và snapshot
      ghi sau mốc đó, nên `observed > latest` ⇒ không stale.
- [x] **M4 đã nâng Medium → HIGH và thành blocker** (quyết 2026-08-14). Giữ nguyên ID `M4`
      để tham chiếu chéo không gãy. Audit + plan đã cập nhật; "Nên promote thành top-level
      blocker" giờ có 4 mục, thêm *broker ledger divergence*.
- [x] **Làm M4 frontend TRƯỚC T9/T10** — đã làm đúng thứ tự đó; M4 đóng ở T11-frontend,
      T9/T10 xong sau. Xem mục Completed đợt 2.

### Key decisions
- **Không chạm code giao dịch** là ràng buộc của đợt audit dashboard, và nó đã giữ suốt Phase 1
  + Phase 2. Hai lần gỡ ràng buộc đều do bạn quyết riêng, không phải Claude tự nới:
  L6 (đổi tên khóa payload trong `runner.py`, không đổi công thức) và sweep Chủ nhật
  (`run_scheduler.py`). Việc sửa test breaker HALT **không** gỡ ràng buộc: chỉ sửa file test,
  `futures/circuit_breaker.py` và `runner.py` không đổi một dòng logic nào.
- **Predicate `stale` neo vào tuổi snapshot, KHÔNG neo vào deadline slot.** Plan viết sai
  lúc đầu: slot chạy mỗi 5 phút nên `latest_slot + 20 phút` luôn ở tương lai suốt active
  window và không bao giờ trôi qua — đo được: snapshot 90 ngày tuổi lúc 14:30 ET vẫn ra
  `False`. Codex bắt được lỗi này và sửa đúng.
- **M4 có bằng chứng thực tế**: bug MNKD→NKD 10× (sửa riêng cùng ngày) làm broker realised
  −$1,400 trong khi sleeve ledger book −$140. Dashboard hiển thị "+$229" và không panel nào
  có thể bắt được — đúng loại divergence M4 mô tả.

### Files touched
REALTIME_DASHBOARD_AUDIT.md, docs/futures/REALTIME_DASHBOARD_FIX_PLAN.md,
docs/futures/OPEN_QUESTIONS.md,
monitor/backend/schedule_status.py, monitor/backend/job_journal_reader.py,
monitor/backend/open_issue_reader.py, monitor/backend/app.py,
monitor/test_realtime_contract.py (mới), monitor/test_realtime_dom.py (mới),
monitor/test_dashboard_backend.py,
global_index/dash/realtime/{index.html,realtime.js,realtime.css}

### Test state (2026-08-15, đo được)
dashboard_backend 133 · realtime_contract 11 · realtime_dom 32 — **tổng 176 passed**.
Baseline lúc bắt đầu audit là 114. Con số trôi vì `test_dashboard_backend.py` được sửa
song song ngoài phạm vi, nên quy tắc là **chỉ được tăng**, không khớp số cứng.
Verify cuối: `node --check` sạch · 0 console error · element bị cắt = `[]` ở cả 1440 và 390.

### Kết quả audit
**20/21 finding đã đóng.** Còn duy nhất **L6** (hoãn có chủ đích, cần quyết định về `runner.py`).
Cộng 4 việc ngoài phạm vi audit gốc: lane `recovered`, test bắt nội dung bị cắt, contract test
payload, guard read-only cho cả 4 dashboard.

### Bài học vận hành (chi tiết ở SCRATCHPAD.md)
- Agent thực thi **hai lần hoàn thành việc mà không báo về** — task tự biến khỏi `status --all`.
  Trạng thái phải đến từ phép đo (mtime + grep dấu mốc + chạy test), không từ báo cáo.
- Backtick trong prompt gửi codex-rescue → shell command substitution → hai writer song song
  trên cùng file. `codex-companion cancel` hỏng dưới Git Bash (`/PID` bị đổi thành đường dẫn),
  phải kill bằng PowerShell.
- Chia việc theo **file** chứ không theo task: sau khi tách rạch ròi (Codex giữ frontend, tôi giữ
  backend + test contract) thì không còn lần đụng độ nào.

---
## Sub-task: Paper Evidence dashboard — audit + sửa (IN PROGRESS 2026-08-15)
Status: IN PROGRESS — phần dashboard đã xong, phần re-freeze HOÃN sang phiên riêng

Báo cáo đầy đủ: **PAPER_DASHBOARD_AUDIT.md** (1.958+ dòng, tiếng Việt, Phụ lục A–J).

### Completed
- [x] Audit gốc: 8 Critical / 8 High / 8 Medium / 5 Low, kèm bảng nhất quán dữ liệu và lỗ hổng test
- [x] **C8 — lỗi nghiêm trọng nhất**: lệnh MNKD định tuyến sang NKD full-size (×10 kích thước).
      Xác nhận từ IBKR `reqContractDetails` + sao kê Flex. Đã sửa; bút toán đối soát −$1.260 hiển thị trên dashboard
- [x] C1–C5, H1–H3, H5–H8, M1, M3–M7, L1–L5 — xem bảng TRẠNG THÁI SỬA CHỮA trong audit
- [x] **Nền tảng tiền broker (G1–G3)**: `paper_pnl_compare` + `pair_fifo` chuyển sang `Proceeds` của sao kê.
      Trước: `paper_minus_flex = 0.00` vì sai multiplier triệt tiêu hai vế. Sau: **+$1.260,00**, khớp bút toán
- [x] **Ngưỡng lỗ go-live** (Phụ lục H): 2 cổng, 21 band, panel document đầy đủ trên dashboard.
      Cổng biên lợi thế vũ trang từ N=20, sàn p01; cổng vận hành không ngưỡng.
      Chặn nhầm **3,55%** đo trên 1.749 phiên
- [x] **`ibkr_symbol` thành trường bắt buộc** (I.1) — `_RAITS_TO_IBKR` suy ra từ `Contract.ibkr`, không còn bảng thứ hai
- [x] **Chống lệch artifact** (I.2) — `source_signature` hash nội dung; banner STALE khi code đổi mà chưa regenerate
- [x] **Panel bằng chứng TWS** (I.3) — coverage 15 → 17 khoá; 4/4 thẻ gap có nút mở panel
- [x] **C5/C6 — `exit_reason`**: lý do thoát chảy được từ engine → signal → trade log.
      `run_maxhold_exit` và `_retry_pending_exits` trước đây **không ghi dòng CLOSE nào**; giờ đều ghi
- [x] **b3 phân loại**: episode mismatch 2026-08-10 = chính C8. Gate `BREACH → EXPLAINED`
- [x] **Warm-cache**: cổng mở 2,2s (trước 40,5s), request đầu 1,06s (trước 84,3s)

- [x] **Spec C1 mới (H3+H4) — duyệt 2026-08-15**: OPEN theo từng mã (N≥20/mã), STP gộp (N≥30),
      trần 5→3 tick, kèm khoảng tin cậy 95%. Mọi ngưỡng mang theo dẫn xuất, hiện trên dashboard
      (Phụ lục K). Nhịp mẫu đo được: 1,87 lệnh/phiên → min_n cũ 100 cần 178–289 phiên cho mục tiêu 60
- [x] **Đọc log tăng dần**: quét per-file memo theo mtime+size. **22s → 0,03s** khi một file ghi thêm.
      Kèm phát hiện seam merge B3 CÓ kích hoạt 3 lần (bỏ nó = bịa ra mismatch không tồn tại)
- [x] **Tách log test**: chặn ở nguồn đã có sẵn và đang chạy (không log nào sau 2026-08-10 nhiễm).
      Lỗ hổng thật là không test nào giữ nó → thêm lh9/lh10/lh11
- [x] **DOM smoke test đóng gói**: `monitor/test_paper_dom.py`, 7 test, chromium thật + payload thật.
      **Bắt lỗi thật ngay lần đầu**: bản sửa M4 chỉ phủ ≤680px; ở 1024px `rejection-table` cắt mất
      117px (nguyên một cột) không đọc được. Đã sửa `overflow-x: auto` toàn cục

### In progress / cần quyết định
- [ ] **Mức cho phép suy giảm Calmar** — thuộc phần re-freeze đã hoãn
- [ ] Tooltip trên mobile — mọi định nghĩa metric vô hình khi không có hover (mục UI/UX #10)

---
## Sub-task: Cổng re-freeze HMM — truy nguyên cơ sở đo + quyết định refit (2026-08-15)
Status: IN PROGRESS

### Completed
- [x] **Truy nguyên toàn bộ cơ sở đo** → `docs/futures/CALMAR_PROVENANCE.md` (mới).
      9 trục làm Calmar đổi giá trị kèm ngày đổi; xuất xứ từng con số; 3 lỗi cấu trúc
      trong `run_verify`; 6 doc-drift (D1–D6). Đóng dòng ⚠️ treo từ 2026-07-05 trong
      `FUTURES_TRUST_AUDIT_TODO.md` (*"fit_A degradation floor | 2.38 | unclear"*)
- [x] **`CALMAR_FLOOR = 2.38` truy ra gốc**: là floor fit_A đo 2026-07-02 trên data
      **incremental, 1-tick**, look-ahead, bar-0 exit, nkd cap 2%. Bị deprecate công khai
      ở `DECISIONS.md:128` **4 ngày sau khi được hardcode**; `git log -S` cho đúng 1 commit
      (`e773e3b`) → chưa bao giờ sửa. Chuỗi floor: 2.38 → 2.04 → 1.53 → 1.57 → **1.65**
      ⚠️ **Bẫy đọc doc**: có HAI run khác hẳn nhau cùng làm tròn ra 2.38 (fit_A floor $47,838
      1-tick / fit_C baseline $47,186 2-tick). `DECISIONS.md:37` từ chối **cả hai** làm floor
- [x] **`registry.calmar = 2.744` truy ra gốc**: sinh bởi `run_verify` 2026-07-06, 2-tick,
      **có stress**, replay toàn lịch sử, data incremental — trước cả 3 bản sửa engine.
      Commit `5d137b2` xác nhận (*"baseline 52936/2.744"*). Không tái tạo được **do thiết kế**
- [x] **Dựng lại phép đo L11** → `futures/compare_refit.py` (mới, committed).
      Đo trong khung production, hai cửa sổ, lưu kèm cơ sở đo. Self-check đã **chứng minh đỏ được**
      (SC1 đỏ với CSV cũ; SC2 đỏ khi fit_new == fit_prev — cả hai dừng trước khi fit)
- [x] **VERDICT: HOLD — KHÔNG refit 2025-12-31.** L11 forward 2026-01-02..08-13:
      **9/154 = 5.84%** (ngưỡng 15–20%). Tái tạo lần đo 2026-07-09 (8/126 = 6.35%) —
      thêm ~6 tuần dữ liệu chỉ thêm **đúng 1 ngày** flip. Bản sửa CSV 2026-08-13 không lật kết luận.
      Phân rã theo năm: flip rải đều **2–6% khắp 2018–2026**, không dồn vào đuôi → **nhiễu fit,
      không phải thông tin mới**. Ghi vào `DECISIONS.md`

- [x] **Đo sàn nhiễu** → `futures/measure_fit_noise.py` (mới) + `fit_noise_report.{txt,json}`.
      5 seed, CÙNG `fit_end=2024-12-31`, 10 cặp. `SC-FIDELITY` chứng minh bản chép vòng lặp
      == production (seed 42 → hash `b70204f002b1f717`, trùng `label_regimes` thật)
      - Cửa sổ L11 (2026+): nhiễu min 2.60% / **trung vị 5.8442%** / max 12.34%
      - Cửa sổ gate (2019+): nhiễu min 1.20% / trung vị 3.32% / **max 7.58%**
      - **Tín hiệu L11 = 5.8442% = TRÙNG trung vị nhiễu đến 4 chữ số thập phân** — cùng mẫu số
        154 ngày, cùng **9 ngày** khác. Đổi `fit_end` 2024→2025 đổi đúng bằng số nhãn 2026 mà
        đổi seed 42→123 đổi → HOLD không chỉ "dưới ngưỡng" mà là **không mang thông tin nào**
      - Tín hiệu gate 3.87% cũng nằm giữa phân bố nhiễu (giữa cặp 42v123=3.40% và 1v7=4.34%)

### Phát hiện mới — cần quyết định
- [ ] **`GATE_AUTO_PCT = 5.0` nằm DƯỚI trần nhiễu 7.58%** trên chính cửa sổ gate.
      Chạy lại **y hệt cấu hình cũ** với seed khác có thể ra `VERIFY` (5-15%). Gate bắn được
      trên nhiễu thuần và không phát hiện nổi thay đổi thật cỡ nhỏ. Ngưỡng 5% chưa bao giờ
      được neo vào sàn nhiễu. Ngưỡng L11 15-20% cũng vậy — cần sửa `LESSONS.md` L11
- [ ] **Phân bố nhãn đổi theo seed đáng kể**: Stress **253-321 ngày** (11.7%-14.8%),
      Calm 40.0%-44.3%. Production ghim seed 42 (`engine.RANDOM_SEED`) — đúng cho tái tạo,
      nhưng chuỗi regime đang chạy là **một lần rút** từ phân bố khá rộng.
      Ảnh hưởng P&L **CHƯA đo** → cần deploy_sim từng seed mới biết có material không
- [x] Trấn an: A→C 17.16% vượt trần nhiễu 7.58% → quyết định nâng fit_C **vẫn đứng**
      (lưu ý: khác cửa sổ + khác data, nên là dấu hiệu chứ chưa phải chứng minh)

### Completed (tiếp — 2026-08-15)
- [x] **P&L theo seed** (`futures/measure_seed_pnl.py`): 5 seed, cùng fit_end, cơ sở ghim.
      SC-ANCHOR PASS (seed 42 = $42,459/1.72 đúng INVARIANTS). Calmar **1.56–1.72**,
      **2/5 dưới sàn 1.65**. PF trải 0.68%, Sharpe 2.42%, Calmar 9.47% → **hệ ổn định,
      thước đo nhiễu**: mẫu số Calmar là MaxDD, một ngày, chỉ nhận 2 giá trị qua 5 lần chạy
- [x] **Cổng đổi sang đo theo cặp + 3 thước** (`paired_verdict`), `PAIRED_TOL=0.05` suy từ
      1.65/1.72=95.9%; `CALMAR_FLOOR` 2.38 → **1.50** (chặn thảm hoạ, dưới đáy nhiễu 1.56)
- [x] **G2 đổi động từ**: `MODEL AGE URGENT → CHECK DUE`, trỏ vào `compare_refit.py`
      thay vì `refreeze.py`. Ngưỡng 12/18 tháng giữ nguyên
- [x] Test: refreeze **87/87**, hmm_stale **42/42**. Mutation test cả T13 lẫn T14 → đúng số test đỏ

### Completed (đợt cuối — 2026-08-15)
- [x] **Sàn nhiễu P95 trên 30 seed** (435 cặp): L11 P95 **11.04%**, gate P95 **9.09%**.
      Verdict đổi từ so `max` sang so **P95** (max của mẫu nhỏ là ước lượng đuôi tệ nhất).
      ⚠️ max 30-seed (11.69%) KHÔNG phải trần thật — bộ seed đó thiếu cặp sinh ra 12.34%;
      **cực đại đã quan sát = 12.34%**. Ngưỡng L11 15–20% nằm TRÊN P95 → ngưỡng vốn đúng
- [x] **`detect_regime_miss.py`** — L11 điều kiện 2. Ba lớp ghi rõ độ độc lập; neo IS
      **AUC 0.8943** trên vol TƯƠNG LAI (lần đầu HMM được kiểm chứng độc lập trong dự án).
      Hiện: *không đánh giá được (thị trường chỉ vừa chạm)* — 4 ngày Stress/252, sụt sâu nhất
      −9.13% vs ngưỡng IS-Stress −9.10%, model CÓ bắn đúng chỗ → **không phải model mù**
- [x] **G2 trỏ vào cả hai công cụ** (`f4b2677`) — điều kiện 1 không thay thế được điều kiện 2,
      vì `compare_refit` so HMM với chính HMM
- [x] **Sàn 1.65 khai đúng bản chất** (`0af152c`) — truy vào chỗ tiêu thụ mới thấy nó **chưa
      từng gate gì**: `analytics.js` chỉ hiển thị, `running_metrics.calmar = null`.
      Và lệch nền giữa hai ô lớn hơn nhiễu seed nhiều (frozen/`--end 2024-12-31`/no-stress
      vs đầy đủ/có stress). Nhãn `Floor fit_A` → `Backtest fit_A`. **Giá trị không đổi**
- [x] **D1, D2, D6** (`5c901f0`) — `dump_state` đọc `refreeze_pending.json` thật thay hardcode,
      fail-closed; PIPELINE_FLOW bỏ hai câu sai. `test_operational_fixes` **135/135** (từ 126)

### Next steps
- [ ] **So paper với backtest trên đúng cửa sổ paper** — bản chữa thật cho phần theo dõi
      (`paper_vs_backtest.expected_equity` / `divergence_pct` đang `null` chứ không phải
      không tồn tại). **Chờ dữ liệu**, không chờ quyết định
- [ ] Trigger mở lại câu hỏi refit: **cửa sổ 12 tháng đầu tiên tích đủ ≥10 ngày Stress**
      (hiện 4). Lúc đó `detect_regime_miss.py` mới phát verdict thật
- [ ] `.gitignore` chưa chặn `tmp_*.png` (6,7 MB), `*_report.txt`, `runner_events_*.jsonl` —
      nhiễu này đã che 7 file trong index và làm tôi commit nhầm một lần
- [ ] 15 file tên hỏng ở thư mục gốc (mảnh JS do shell vỡ quoting), 14/15 rỗng
- [ ] Mạch `exit_reason` mới commit **đầu ghi** (`a450712`), đầu nguồn còn ngoài
      (`swing_tf.py` +60, `signal_layer.py`, `test_exit_reason.py` chưa track)
- [ ] Thêm trường cơ sở đo vào `FreezeRecord` (slippage / data_dir / end / stress / commit)
- [ ] V1–V3: ghim `run_verify` vào cơ sở cố định (đang bật stress + không cắt `--end` + data_dir trôi)
- [ ] D6: nối `refreeze_pending.json` vào `dump_state` — `runner.py:2479` đang hardcode `False`
- [ ] **G2 cần quyết định có chủ đích**: 20 tháng > `G2_HARD_MONTHS = 18`, dashboard đang bắn
      `MODEL AGE URGENT — schedule re-freeze immediately` mỗi ngày trong khi đáp án đo được là
      "không refit". Cảnh báo mà đáp án đúng là phớt lờ sẽ dạy người vận hành phớt lờ mọi cảnh báo

### Key decisions
- Refit trigger là **model cũ sai**, không phải **có data mới** (L11). G2 kêu ≠ lý do refit
- `run_gate` trả `AUTO_APPROVE 3.87%` cho đúng lần refit mà L11 nói không nên làm.
  Gate không có câu hỏi "có nên refit không" — nó chỉ hỏi "fit mới có khác đủ đáng sợ không"
- Không sửa dòng production nào trong phiên này: `refreeze.py` / `basket.py` / registry còn nguyên

### Files touched
Mới: `docs/futures/CALMAR_PROVENANCE.md`, `futures/compare_refit.py`,
`futures/compare_refit_report.{txt,json}`. Sửa: `docs/futures/DECISIONS.md` (2 entry HMM)

---

## Sub-task: Rà soát runner — CHỈ ĐỌC (2026-08-15)
Status: DONE (rà soát) — **các ô chưa tick bên dưới là hiện trạng NGÀY RÀ SOÁT, giữ làm bản ghi.
Kết quả sửa: xem mục "Sửa theo rà soát runner (2026-08-16)" ngay dưới khối này — 20/22 đã đóng.**

Báo cáo đầy đủ: `RUNNER_AUDIT.md`. Kịch bản tái lập ở scratchpad phiên (lệnh trong §6 của báo cáo).
Không sửa code / cấu hình / state file, không kết nối IBKR, không xoá parquet.

### Chặn cứng — theo thứ tự gấp
- [ ] **C1 — HẠN CHÓT 04/9/2026 (còn 20 ngày).** `ROLL_SCHEDULE` có khoá `MNK` và `NKD`
      nhưng **không có `MNKD`**, mà `runner.py:1229` truyền `pos.inst = "MNKD"`
      (`run_live_day.py:88`). ⇒ vị thế Nikkei **không bao giờ roll**.
      Nặng hơn: `send_order`/`place_stop`/`fetch_bars` đi qua `_front_month_contract`
      **có** biết ngày roll, nên **từ 04/9 lệnh đi vào 202612 trong khi vị thế còn ở 202609** —
      lệnh CLOSE kế tiếp sẽ **MỞ** một short thay vì đóng. Đo: `repro_c1.py`.
      Lưu ý lịch trực: runbook nhắm 11/9 + khung 13:45–14:05 ET; roll Nikkei là 04/9 khung đêm.
      Và bài diễn tập `exercise_rollover_live` dùng **MNQ** (TASK.md:3269) nên không thể lộ ra nó.
- [ ] **C2 — không cần dịp đặc biệt.** `send_order` **không bao giờ** trả `"FAILED"` cho lệnh OPEN
      (`ibkr_broker.py:678/:724/:741` đều trả `"CANCELLED"`), nên `runner.py:1770` là code chết.
      Một lệnh vào hết 30s chờ để lại **vị thế ma**: sổ runner có, broker không, `entry_price=None`,
      **0 dòng trade_log, 0 sự kiện, 0 dòng ERROR**, và được ghi xuống `live_positions.json`.
      Ngày thoát → gửi lệnh CLOSE cho vị thế không tồn tại = mở vị thế ngược chiều không stop.
      Đo: `repro_c2.py` (có cột đối chứng FILLED để chứng minh phép đo phân biệt được).
- [ ] **H2 — công tắc D5 không được nối.** `stop_path` xuất hiện **0 lần** trong cả ba entry point
      (`run_live_day.py`, `run_maxhold_exit.py`, `run_stop_repair.py`), nên `_stop_path is None`
      và `STOP_TRADING` không có tác dụng. `OPERATIONS.md:89` có runbook; `STATUS.md:76` đếm nó
      vào "16 cơ chế an toàn (grep-verified)". Đây là kế hoạch ứng cứu cho chính C1 và C2.

### Nợ trước khi số liệu trích dẫn được
- [ ] **H1 — đường roll là call site thứ TƯ dựng hợp đồng bằng tay.** Phụ lục F gom ba,
      bỏ sót `_handle_rollover` (`ibkr_broker.py:1427,1480`): dùng `inst` thô làm mã IBKR,
      ép `exchange="CME"` (MYM phải là CBOT), không kiểm `conId`. Sửa C1 mà không sửa H1
      = đổi "không roll" thành "roll vào hợp đồng không giải được".
- [ ] **H4 — còn HAI đường đóng lệnh book tiền mà không ghi trade_log**
      (khác ba đường đã sửa 15/8): `runner.py:830` (B3 stop FILLED nhưng mất bản ghi khớp)
      và `runner.py:1644-1662` (vào+ra cùng phiên). Đo: `repro_h4.py`.
      Hệ quả: `paper_epoch_closed_realized` thiên lệch có hệ thống, và
      `ledger_offset_explanation: MATCH_PRE_EPOCH_CARRY_FILL` sẽ nhận sai khoản lệch đó.
- [ ] **H5 — `subprocess.run` không có `timeout`** (`run_scheduler.py:350`). Một con treo giữ
      `_slot_lock` cả phiên; triệu chứng duy nhất là dòng WARNING trùng hệt lần chồng slot bình thường.
- [ ] **M5 — delta NetLiquidation đo rồi vứt** (`runner.py:1673-1684`), không so với tổng đã book.
      Cặp song song duy nhất còn đủ hai vế mà không có phép đối soát nào — đúng chỗ C8 ($1.260) lẽ ra đã lộ.
- [ ] M1 (khớp một phần → stop theo số **đã đặt**) — ảnh hưởng hiện tại **bằng 0** vì `N_CONTRACTS=1`;
      **chặn của trục scaling**, xếp vào mục B ở §KHỞI ĐIỂM.
- [ ] M2 / M3 / M4 / M6 / L1–L4 — xem `RUNNER_AUDIT.md` §1.

### Key decisions
- **Không sửa gì trong phiên này.** Yêu cầu là rà soát chỉ-đọc; C1 có hạn chót nhưng sửa nó
  đúng cách cần chạm cả H1, và đó là quyết định của chủ dự án chứ không phải hệ quả của một bản audit.
- **H3 không tính là phát hiện mới** — đã có ở `TASK.md:3950` (D6). Đợt này chỉ định lượng:
  nó là một cổng go-live đang báo PASS, và test phủ nó assert `isinstance(False, bool)`.

### Lỗ hổng test (nền: **518/518 PASS, không loại trừ tệp nào**, trong lúc mọi mục trên đang đúng)
- `test_runner_event_log::test_incomplete_tail_is_not_extended` **không còn hỏng** — commit
  `a450712` đã sửa. Nếu dùng danh sách "đã biết rồi" làm mốc thì gạch mục này.
- **H3 có 0 phép kiểm có khả năng thất bại trên toàn bộ 46 tệp** (đã đóng lỗ hổng "chưa đo"):
  `test_operational_fixes.py:891` assert `isinstance(False, bool)`;
  `test_event_playback.py:733` assert khoá `refreeze` **có mặt**. Không cái nào so với
  `models/hmm/refreeze_pending.json`, thứ duy nhất làm cổng này có nghĩa.
- `test_stp.py:224` `test_stp4_no_stp_when_open_cancelled` — **thân hàm không có một `assert` nào**.
  Viết đúng cho kịch bản C2, kiểm đúng một điều (stop không được đặt), bỏ trống bốn câu hỏi tạo nên C2.
- `test_operational_fixes.py:891` — assert `isinstance(False, bool)`. Không thể đỏ.
- `test_rollover.py:198-201` — tra lịch roll bằng khoá `"NKD"`, khoá mà production **không dùng** từ 14/8.
  Chính đây là chỗ C1 lọt qua.
- Không test nào chạy `IBKRBroker._handle_rollover` thật (cả hai tệp đều cài bản giả trên mock).
- Không test nào nhắc tới `stop_path` / `STOP_FILE`.
- **Đề xuất một test chặn cả bốn dạng:** dựng runner bằng **đúng** danh sách tham số
  `run_live_day.py:699` truyền, rồi assert từng cơ chế an toàn thật sự được nối.
  Hôm nay không test nào nhìn vào `run_live_day.py`.

### Files touched
Mới: `RUNNER_AUDIT.md`. Sửa: `TASK.md` (mục này). **Không tệp .py nào bị sửa.**

### Đọc kỹ trước khi tiếp
- **`exit_path_coverage` vẫn STRUCTURAL_GAP** và **đúng như vậy**: fix `exit_reason` chỉ áp cho các
  lần đóng **tương lai**; 4 CLOSE cũ không dán nhãn ngược được. Gate sẽ tự mở khi tích đủ mẫu mới
- **Quét cold-cache 60–85s vẫn còn**, chỉ mới vá bằng warm-up lúc khởi động. Cache hỏng mỗi lần
  scheduler ghi log (~5 phút). Cách chữa thật là **đọc log tăng dần**. Chưa làm — không tự thêm
  vòng re-warm định kỳ vì chiếm ~20% một core thường trực trên máy chạy giao dịch thật
- **Dashboard đọc `monitor/paper_pnl_compare.json`** (artifact sinh sẵn). Sửa `paper_pnl_compare.py`
  hoặc `statement.py` xong **phải chạy lại** `python monitor/paper_pnl_compare.py`

### Test state (2026-08-15 cuối phiên, đo được)
Toàn bộ `monitor/ + global_index/ + futures/`: **777 passed, 0 failed** (37 phút).
`monitor/` riêng: **243 passed** (từ 89 lúc bắt đầu audit).
Deselect duy nhất: `test_runner_event_log::test_incomplete_tail_is_not_extended` — hỏng sẵn từ baseline,
đã xác minh không liên quan (file test đó không tham chiếu statement/proceeds/point_value).

### Trạng thái gate lúc kết phiên
```
PENDING         paper_duration      5/60 ngày
PENDING         regime_coverage     chờ một phiên Stress
STRUCTURAL_GAP  exit_path_coverage  fix exit_reason chỉ áp cho lần đóng TƯƠNG LAI
QUALITY_BREACH  c1_slippage         4/4 mã vượt trần 3 tick trên n=1..2
EXPLAINED       b3_reconcile        episode mismatch = chính C8, đã phân loại
PENDING         stp_verification    1/10 phiên
PENDING         tws_restart_nights  0/10 đêm
```
Hai coverage BREACH (`data_freshness`, `open_incidents`) cùng một gốc: model HMM 20 tháng — **nợ, không phải halt**.

### (cũ) Test state giữa phiên
`monitor/` 162 passed · `global_index/ + futures/` **538 passed, 0 failed**
(36 phút; deselect duy nhất `test_runner_event_log::test_incomplete_tail_is_not_extended` hỏng sẵn từ baseline).
Mọi fix đều **mutation-test**: gỡ fix → xác nhận đúng test đỏ → khôi phục.

### Files touched
30 file, +2.593 / −436. Mới: `PAPER_DASHBOARD_AUDIT.md`, `global_index/test_exit_reason.py`,
`futures/verify_current_freeze.py`.

### Bổ sung 2026-08-15: bảng tự cập nhật khi có dữ liệu mới
- [x] **Cron**: sau job báo cáo phiên → tải sao kê broker → dựng lại đối chiếu P&L.
      Thừa hưởng cờ chống trùng, lưới an toàn 23:55, và lắng nghe cả sự kiện lỗi.
      Mọi lỗi chỉ ghi log — lịch này là tiến trình đặt lệnh thật.
- [x] **Dấu vân tay dữ liệu**: artifact đóng dấu ngày cuối trade_log + paper_history +
      tên tệp sao kê. Dữ liệu mới hơn artifact → banner STALE. Vì cron có thể chết, và
      lúc cron chết là lúc cảnh báo cần nhất.
- [x] CỐ Ý không tự động, có test giữ: **baseline backtest** (là mốc so sánh, 21 band
      ngưỡng đóng băng từ nó) và **paper_inputs.json** (lời chứng thực của con người).
- Test: 800 passed, 0 failed (toàn bộ monitor + global_index + futures, 17 phút).

---
## Sub-task: Sửa theo rà soát runner (2026-08-16)
Status: DONE — **20/22 đóng, 2 cố ý để lại**. Đã push tới `0e0051c`.

### Ba chặn go-live: đã đóng cả ba
- [x] **C1 — Nikkei không bao giờ roll.** Tra lịch roll giờ đi qua đúng phép quy đổi mã mà mọi
      đường khác đã dùng (`MNKD → MNK`), thay vì tra thẳng bằng tên runner.
- [x] **H1 — đường roll là call site thứ TƯ dựng hợp đồng bằng tay.** Gom về một bộ dựng duy nhất,
      có tra sàn (MYM là CBOT chứ không phải CME). Sửa C1 mà bỏ H1 chỉ đổi "không roll" thành
      "roll vào hợp đồng không giải được" — nên hai mục này đi cùng một lượt.
- [x] **C2 — lệnh vào hết giờ chờ để lại vị thế ma.** Vị thế chưa có giá vào bị gỡ khỏi sổ,
      và phát một ALERT. Trước đó: 0 dòng trade_log, 0 sự kiện, 0 dòng ERROR.
- [x] **H2 — công tắc dừng không được nối.** Một hằng số duy nhất, ba entry point cùng nhập.
      Trước đó `STOP_TRADING` không có tác dụng ở bất kỳ đâu.

### Còn lại đã đóng
H4 (hai đường đóng lệnh book tiền mà không ghi sổ) · H5 (`subprocess` không có hạn giờ, một con treo
giữ khoá slot cả phiên) · M2 · M3 (tìm khớp lệnh không lọc theo hợp đồng) · M4 (phát hiện lệch tháng,
không tự đồng bộ) · M5 (delta NetLiquidation đo rồi vứt — ngưỡng $250 lấy từ phân bố sau khi sửa
định tuyến MNKD, không phải từ p99 của cả chuỗi) · M6 · L1 · L2 · L4 · C6 · thống nhất lược đồ bản ghi CLOSE.

### Cố ý để lại
- **M1** (khớp một phần → stop theo số đã đặt): ảnh hưởng hiện tại **bằng 0** vì `N_CONTRACTS=1`.
  Là chặn của trục scaling, không phải của go-live.
- **L3**: cùng lý do — chỉ có nghĩa khi số hợp đồng > 1.

### Ngoài phạm vi audit, phát sinh trong phiên
- [x] **Vì sao job 18:30 ET chủ nhật không chạy**: scheduler chạy từ 13/8 04:30, cron sửa 15/8 01:10.
      APScheduler chỉ nạp cron lúc khởi tiến trình ⇒ bản đang chạy **không có** job đó.
      21 lần restart backend đi qua mà không ai thấy, vì mọi chỉ báo đều nói "running".
- [x] `ops.py restart` giờ hạ cả scheduler lẫn runner theo mặc định (`--no-scheduler` để giữ lại).
      Trước đó phải nhớ `--scheduler`, và không nhớ thì im lặng không làm gì.
- [x] Header bảng giám sát hiện tuổi scheduler. Có `RUNNING OLD CRON` khi mã trên đĩa mới hơn
      tiến trình, và `×N RUNNING` khi có nhiều hơn một.
- [x] **Hồi quy hiệu năng do chính mục trên gây ra**: `psutil.process_iter` chạy mỗi request,
      endpoint **23.556ms**. Cache TTL 60s, đọc đầu đồng bộ rồi làm mới nền ⇒ **0,6ms**.
      Và bộ so khớp ban đầu khớp chuỗi con, trả 5 pid trên máy chỉ có 1 scheduler (kể cả script đo
      của chính tôi) ⇒ sẽ hiện "Scheduler ×5 RUNNING" màu đỏ. Đổi sang phân tích `argv`.

### Key decisions
- **Ngưỡng đối soát $250, không phải $889.** p99 của cả 267 quan sát là $889, nhưng cắt tại 14/8
  cho thấy cái đuôi béo **chính là** lỗi định tuyến MNKD. Lấy p99 của cả chuỗi là lấy ngưỡng từ
  chính lỗi vừa sửa.
- **M4 phát hiện lệch tháng chứ không tự đồng bộ.** Tự sửa hợp đồng dưới chân một phiên đang chạy
  là đúng loại việc phải để người quyết.
- **Mọi test mới phải chứng minh được nó đỏ được**, bằng monkeypatch trong tiến trình.
  Test công tắc dừng của tôi ban đầu xanh **vì lý do sai** — broker giả không uỷ quyền `send_order`
  nên sổ vị thế rỗng, B3 báo lệch và chặn lệnh vào. Chỉ có phép đối chứng ("không có tệp dừng thì
  lệnh phải đi ra") mới lộ ra.

### Test state (2026-08-16 cuối phiên, đo được)
Toàn bộ `global_index/ + futures/ + monitor/`: **854 passed, 0 failed** (24 phút 19).
Không deselect tệp nào. Chạy lại riêng `monitor/test_realtime_dom.py` + `test_dashboard_backend.py`
sau lần sửa cuối: 223 passed.

### Xác minh trên trình duyệt thật (viewport 487)
Chip mới mép phải 471 < 487, không tràn; trang không trượt ngang; **0 phần tử bị cắt thật**
(bảng vượt mép nằm trong `DIV.table-wrap` có `overflow-x: auto`, cuộn được).

### Files touched
`global_index/runner.py`, `ibkr_broker.py`, `broker.py`, `run_scheduler.py`,
`monitor/ops.py`, `monitor/backend/schedule_status.py`,
`global_index/dash/realtime/index.html` + `realtime.js`, `RUNNER_AUDIT.md`,
`docs/futures/DRYRUN_SUNDAY.md` (mới), `global_index/test_kill_switch.py` (mới),
`global_index/test_contract_month.py` (mới) + 10 tệp test sửa.

---
## Sub-task: Rà soát THIẾT KẾ UI/UX bảng giám sát (2026-08-16)
Status: DONE — chỉ đọc code + đo trên trình duyệt, KHÔNG sửa gì

### Đã làm
- [x] Đo 5 trang (`/realtime`, `/paper`, `/analytics`, `/reports`, `/`) ở 1440px và 390px thật
      (device emulation, vì cửa sổ có sàn ~502px). Thêm sweep 1366/1920/1922 cho hàng đầu trang.
- [x] Viết `DASHBOARD_UX_REVIEW.md` — 8 vấn đề CHỨC NĂNG + 4 đề xuất THẨM MỸ, tách nhãn rõ,
      kèm bảng "đã đo và không có vấn đề" và thứ tự đề nghị làm.

### Phát hiện chính (đều đo được, không suy đoán)
- Hàng đầu `/realtime` đè chữ ở MỌI bề rộng < 1920px: ở 1366px mục `Reports` bị che 100%,
  `Paper` 84%. Nguyên nhân: ô thứ ba bị chốt sàn 300px + `nowrap` + căn phải → tràn ngược trái.
- Chấm trạng thái mã hoá CHỈ bằng màu; xanh ↔ vàng lệch 6/255 mức xám (tỉ lệ 1.06).
- Hai số to nhất trang (37px, 29px) đều nói "ổn"; cảnh báo thật ở 13–16px.
- Ô an toàn "Protection" bị cắt cụt thành `1 co…` (mất 41px).
- 111/292 nút chữ dưới WCAG AA, gần như toàn bộ do MỘT biến `--dim`; sửa một dòng
  (`#5b6975` → `#728392`) là đạt AA trên mọi nền đang dùng.
- Ở 390px, liên kết `Paper reconcile` bị cắt 41px và không cuộn tới được.
- Vùng bấm điều hướng cao 12px (chuẩn 44px).

### Đã đo và KHÔNG có vấn đề (khỏi rà lại)
- `tabular-nums` không cần: cả 7 phông đều đẳng rộng chữ số.
- Bảng rộng đều có khối cuộn ngang riêng, nội dung tới được (cả `/realtime` lẫn `/paper`).
- `/paper`, `/analytics`, `/reports`, `/`: 0 đè chữ, 0 mất nội dung ở cả hai bề rộng.

### Next steps (nếu quyết định sửa)
- [ ] Ưu tiên: hình dạng cho trạng thái → hàng đầu trang → nâng `--dim` → bỏ cắt cụt.
- [ ] Đảo ngôi thứ vùng màn hình đầu (động bố cục, cần bàn trước).

### Files touched
DASHBOARD_UX_REVIEW.md (mới), TASK.md, SCRATCHPAD.md — KHÔNG đụng file nào trong `dash/**`

---
## Sub-task: Khung route `/realtime-next` để thiết kế lại (2026-08-16)
Status: DONE phần khung — chưa đổi thiết kế gì, có chủ ý

### Đã làm
- [x] `global_index/dash/realtime-next/index.html` — bản sao của trang realtime, thân trang
      giống hệt từng byte, chỉ đổi phần head.
- [x] `global_index/dash/realtime-next/next.css` — lớp đè, hiện chỉ có MỘT luật (dấu
      "· NEXT" cạnh nhãn PAPER) để chứng minh lớp đè đã được nạp.
- [x] `monitor/backend/app.py` — thêm route `/realtime-next` (4 dòng + chú thích).

### Quyết định kiến trúc: LỚP ĐÈ, không nhân bản
- Trang mới nạp CHUNG `/dash/realtime/realtime.css` và `/dash/realtime/realtime.js`.
  Lý do: `realtime.css` là stylesheet nền của CẢ 5 trang, nhân bản 593 dòng đó là tạo ra
  hai bản sẽ trôi khỏi nhau. Chỉ HTML được nhân bản, vì đổi cấu trúc là việc của HTML.
- Không cần đụng backend để phục vụ asset: route `/dash/<path:filename>` đã bắt sẵn.
- Route mới qua `test_backend_routes_are_read_only` sẵn (chỉ đòi mọi route là GET).

### Ràng buộc phải giữ khi sửa trên route này
- **Không xoá phần tử khỏi trang.** `realtime.js` lấy phần tử theo id, trả null khi thiếu,
  và nhiều chỗ gán thẳng thuộc tính không kiểm null → thiếu một id là CẢ TRANG chết.
  Muốn giấu thì `display:none` / `hidden`, giữ id lại.
- **Mốc màn hình hẹp phải đúng 680px** — là giao ước với `matchMedia` trong `realtime.js`
  (quyết định có tự mở sẵn sự cố đầu tiên hay không). Mốc khác sẽ tạo dải lệch.

### Đã đo (script self-check, 6 mục, có mục chứng minh phép kiểm ĐỎ được)
SC1 route mới 200 · SC2 route cũ vẫn 200 · SC3 lớp CSS đè được phục vụ ·
SC4 dùng chung nền, không có bản sao css/js · SC5 không đánh rơi id nào (59 = 59) ·
SC5b thân trang giống hệt bản cũ (11678 = 11678 byte) · SC6 phép kiểm đỏ được (404).
Test: `monitor/test_dashboard_backend.py` + `test_realtime_contract.py` → **198 passed**.

### Bẫy đã gặp khi tự kiểm
Phép kiểm đầu so "id mà realtime.js gọi" với "id trong HTML tĩnh" → báo thiếu 3 id.
SAI HƯỚNG: `railClockEt`/`railClockZones` do chính JS tạo lúc chạy và đã có kiểm null;
`schedulerHealth` đã bị xoá có chủ đích. Đổi thành so trang mới với trang cũ mới đúng.

### Files touched
global_index/dash/realtime-next/index.html, global_index/dash/realtime-next/next.css,
monitor/backend/app.py

---
## Sub-task: E1 + nhóm sửa lỗi CSS trên `/realtime-next` (2026-08-16)
Status: DONE — đo xong ở 1440px và 390px, KHÔNG đụng `/realtime`

### Đã làm (toàn bộ trong `next.css`, không sửa nền, không sửa JS)
- [x] **E1** — dòng phán quyết lên đầu trang: `.overview-header` thành cột dọc, dải trạng
      thái `order:-1`. Số sự cố mở tách khỏi câu phán quyết thành thẻ riêng (trước đây
      in cùng sức nặng nên đọc lướt thành tự mâu thuẫn "nominal … 1 issue open").
      Mục Open Issues đưa lên đầu cột để ô "làm gì bây giờ" nằm ngay dưới phán quyết.
- [x] **A2** — trạng thái mã hoá bằng HÌNH DẠNG + chữ: tròn/OK, tam giác/WARN, vuông/FAIL.
- [x] **A1** — hàng đầu trang hết đè chữ (chỉ áp từ 1051px trở lên, xem hồi quy bên dưới).
- [x] **A4** — bỏ cắt cụt 5 chỗ, gồm `1 co…` (ô bảo vệ) và dòng GIÁ LỆNH DỪNG ở 390px
      (mất 179px — `stop 3,020.2 · plan …` chỉ còn một mẩu trong 103px).
- [x] **A5** — `--dim` `#5b6975` → `#728392` (phạm vi route này).
- [x] **A8** — trả lại vòng viền tiêu điểm cho phần tử có chú giải.
- [x] **A6/A7** — dòng đối chiếu môi giới hết bị cắt; vùng bấm điều hướng 12px → 44px.
- [x] Dòng môi giới tràn 181px sang thẻ bên cạnh: nền ĐÃ CÓ bản sửa nhưng thua bộ chọn
      đặc hiệu hơn (`.equity-zone > small`), nên bản sửa đó nằm trong tệp mà chưa bao giờ
      có tác dụng. Phải viết đủ đặc hiệu mới ăn.

### Đo được — cùng một phép đo cho cả hai route
| Chỉ số | /realtime | /realtime-next |
|---|---|---|
| Đè chữ @1440 | **5** | **0** |
| Cắt cụt @1440 | 4 | **0** |
| Chồng lấn hàng đầu @1440 | +240px | −19px (hết) |
| Tương phản dưới AA @1440 | 111/292 | **19/307** |
| Nội dung mất @390 | 1 | **0** |
| Cắt cụt @390 | 3 | **0** |
| Vùng bấm nav dưới 44px @390 | 4 | **0** |

### Ba hồi quy do CHÍNH bản sửa gây ra, đều bắt bằng đo chứ không bằng mắt
1. A1 đổi `grid-template-columns` ở mọi bề rộng → ở 390px thanh điều hướng bị CẮT 270px,
   vì từ 1050px trở xuống nền xếp lại header. Sửa: giới hạn A1 vào `min-width: 1051px`.
2. Dấu nhận biết `· NEXT` đặt `nowrap` → nhãn rộng 106px thay vì 57px, đẩy cột đầu từ
   173px lên 223px, cả hàng vượt khung 35px ở 390px. Sửa: `nowrap` chỉ từ 681px.
3. Chèn chú thích làm đóng comment sớm → 4 dòng thành CSS rác, **nuốt luôn khối @media**
   và mọi chỉ số ở 1440px xấu lại. Bắt được vì đo lại sau mỗi lần sửa.
   → Đã thêm phép kiểm đếm số luật parse được của `next.css` (hiện 39) vào bộ đo.

### Next steps
- [ ] Thêm test ghim: `/realtime-next` 200 + dùng chung nền + không fork css/js
      + đè chữ = 0 ở 1280/1366/1440/1600/390px.
- [ ] A5 (`--dim`) và A8 (focus) nên sửa TẠI CHỖ ở CSS nền vì lợi cho cả 5 trang.
- [ ] Còn lại của phần E: E2 (tách chế độ liếc/điều tra), E3 (đồng hồ theo khung người
      vận hành), E4 (tách phông sans/mono), E6 (thanh rủi ro dạng bullet).
- [ ] 19 nút chữ còn dưới AA — chưa truy nguyên, không thuộc biến `--dim`.

### Files touched
global_index/dash/realtime-next/next.css

---
## Sub-task: E3 — thời gian theo khung người vận hành (2026-08-16)
Status: DONE — đo xong 1440px + 390px

### Đã làm
- [x] `global_index/dash/realtime-next/next.js` (mới) + kiểu trong `next.css`.
- [x] **Dải cửa sổ vào lệnh** ngay dưới dòng phán quyết: "Cửa sổ vào lệnh kế tiếp mở sau
      13 giờ 39 phút · NKD_NIGHT_0110 · 12:10 ngày mai giờ VN · 05:10 UTC". Khi đang trong
      cửa sổ thì đổi sang dải xanh kèm vạch dày bên trái (hình dạng, không chỉ màu).
- [x] **Dòng phụ dưới mỗi mốc lịch**: còn bao lâu + mấy giờ theo giờ Việt Nam.

### Ba luật tự đặt cho next.js
1. CHỈ THÊM nút mới, không sửa/xoá nút của `realtime.js`; luôn dọn nút cũ của chính mình
   trước khi chèn lại (chống nhân bản).
2. KHÔNG suy thời gian từ chữ hiển thị — `<time>` không có thuộc tính datetime, chỉ có
   "Mon 01:10 ET", suy ngược ra ngày là đoán. Mốc tuyệt đối lấy từ `/api/v1/schedule-status`.
3. Bọc try/catch toàn bộ: lớp phụ hỏng thì trang vẫn chạy như chưa có nó.

### Đối chiếu số học với API (bắt buộc trước khi tin)
| Mốc | API (UTC) | Chênh với server_now | Trang hiện | Giờ VN |
|---|---|---|---|---|
| Next job | 22:30Z | 7h02 | "còn 7 giờ 2 phút" ✓ | 05:30 mai ✓ |
| Next decision | 05:10Z 17/8 | 13.71h | "còn 13 giờ 42 phút" ✓ | 12:10 mai ✓ |
| Latest decision | 19:55Z 14/8 | −43h32 | "cách đây 43 giờ 34 phút" ✓ | 02:55 hôm qua ✓ |

"Latest job" CỐ Ý để trống: API không có trường tương ứng, đoán một mốc gần đúng thì tệ
hơn là không hiện gì.

### Hai hồi quy do chính bản sửa gây ra, đều bắt bằng đo
1. Hai phần dòng phụ để chung một hàng (~250px) trong cột 231px → tràn sang ô bên,
   5 chỗ đè chữ. Sửa: mỗi phần một dòng.
2. `.schedule-fact > div` là flex `nowrap` + `space-between` → nút thêm vào thành phần tử
   flex thứ ba và bị ĐẨY SANG PHẢI tới tận cột Nhật ký, 3 chỗ đè chữ. Sửa: cho hàng
   xuống dòng + ép dòng phụ chiếm trọn bề ngang.
   Thêm: khối lịch `overflow:hidden` + hàng cao cố định → cho cao theo nội dung.

### Đo cuối (cả hai bề rộng)
1440px và 390px: đè chữ **0**, cắt cụt **0**, nội dung mất **0**, console **0 lỗi**,
dòng phụ sống sót qua các lượt vẽ lại của realtime.js (3 dòng trước/sau, không trùng lặp).
Test: 198 passed. Bộ tự kiểm route: 7/7 PASS, thân trang vẫn giống hệt (11678 byte).

### Xác nhận không đụng nền
`git diff --stat -- global_index/dash/realtime/` → **trống**. Chỉ `monitor/backend/app.py`
(thêm route) và thư mục mới `global_index/dash/realtime-next/`.

### Files touched
global_index/dash/realtime-next/next.js (mới), global_index/dash/realtime-next/next.css,
global_index/dash/realtime-next/index.html

---
## Sub-task: E2 + E4 + E6 — hết phần thiết kế đã lên kế hoạch (2026-08-16)
Status: DONE — phần A và phần E đều đã làm hết trên `/realtime-next`

### Đã làm
- [x] **E2 — tách "liếc" khỏi "điều tra".** Nhóm liếc lên trước (sự cố đang mở → vị thế
      và mức bảo vệ), nhóm điều tra xuống sau (lịch chạy → quyết định hôm nay → sổ lệnh),
      kèm một ranh giới nói thẳng: "▽ Từ đây trở xuống là chi tiết để điều tra".
      Không giấu gì, chỉ xếp sau.
- [x] **E4 — tách phông văn xuôi khỏi phông số.** `--sans` trỏ vào phông sans thật rồi áp
      cho mô tả sự cố, ô Impact/Action, tóm tắt và mô tả nhật ký. Số, mã hợp đồng, mốc
      thời gian và **dòng log bằng chứng** giữ nguyên mono (loại trừ có chủ ý).
      Đo xác nhận: văn xuôi = Segoe UI, dòng log = Cascadia Mono.
- [x] **E6 — thanh rủi ro nói ra ngưỡng.** Thanh 5px → 9px có ba vùng nền + vạch mốc,
      kèm NHÃN CHỮ "an toàn / theo dõi / vượt hạn". Hai mốc 66% và 100% lấy đúng ngưỡng
      `realtime.js` đang dùng để đổi lớp thanh — không phát minh ngưỡng mới.

### Lỗi có sẵn phát hiện thêm khi làm E6
Hàng "HMM fit" trong Model Inputs: lưới hai cột nhưng **cột nhãn tính ra 0px** vì giá trị
chiếm hết 225px. Nhãn bị ép rộng 0 nên chữ tràn ra ngoài hộp và giá trị vượt mép hàng
46px — nhìn ra thành chữ chồng chữ. Đã cho cột nhãn một sàn 58px và cho giá trị xuống dòng.
Lỗi này có từ đầu, không phải do các bản sửa của phiên này.

### Hai lần phải sửa lại chính mình
1. Neo nhãn thang đo vào vạch 66% bằng `flex-basis: 66%` → chữ "an toàn" ngắn nên phần
   thừa đẩy hai nhãn sau xuống dòng, ở CẢ 1440px lẫn 390px. Đổi sang dàn đều một hàng.
2. Ba nhãn thang đo không đủ chỗ ở 390px → nhãn cuối bị cắt. Cho xuống dòng thay vì cắt.

### Đo cuối — 1440px và 390px
Đè chữ **0** · cắt cụt **0** · nội dung mất **0** · vùng bấm nav dưới 44px **0** ·
console **0 lỗi** · tương phản dưới AA **19/303** (từ 111/292).
Bộ tự kiểm route **7/7 PASS**, thân trang vẫn giống hệt bản gốc (11678 byte).
Test: **198 passed**.

### Còn treo
- [ ] 19 nút chữ dưới AA — chưa truy nguyên, không thuộc biến `--dim`.
- [ ] Chưa có test ghim route mới (200 + dùng chung nền + không fork + đè chữ = 0 ở
      1280/1366/1440/1600/390px). Không có phép kiểm đè chữ thì A1 quay lại mà test vẫn xanh.
- [ ] A5 (`--dim`) và A8 (focus) vẫn nên sửa TẠI CHỖ ở CSS nền vì lợi cho cả 5 trang.

### Files touched
global_index/dash/realtime-next/next.css, global_index/dash/realtime-next/next.js

---
## Sub-task: Bộ xem trạng thái + thẻ bằng chứng + chuyển UI sang tiếng Anh (2026-08-16)
Status: DONE

### 1. Bộ xem trạng thái giả (làm TRƯỚC, theo quyết định của chủ dự án)
`preview.html` + `preview-states.js` + `preview.css`. Tám kịch bản: nominal, evidence
missing, runner stale, 6 NKD slots failed, 6 failed-recovered, breaker HALT, entries
blocked, data source down.
- **Chặn fetch rồi BIẾN ĐỔI phản hồi thật**, không bịa payload — bịa thì hình dạng lệch
  API và thiết kế được kiểm trên thứ không tồn tại.
- Mỗi kịch bản có **kết quả dự đoán trước** (`expect`) → kiểm được là bộ xem thật sự bật
  được trạng thái đó. Đo: **8/8 khớp**.
- Trang vận hành **không chứa một dòng mã giả lập nào** — script chỉ có trong preview.html.
- Bản đồ trường→trạng thái đọc từ chính realtime.js, không suy đoán.

### 2. Thẻ bằng chứng cạnh phán quyết
Vấn đề đo được: khi 6 slot NKD hỏng, phán quyết "scheduler attention required" nằm trên
cùng còn bộ đếm sự cố ở **1285px** và nhãn phục hồi ở **2068px** — cách một tới hai màn.
- Thẻ gộp theo **stream** (`NKD_NIGHT_0205` → `NKD_NIGHT`), đúng khoá backend dùng để
  xác định phục hồi. Tự đặt khoá khác sẽ khiến thẻ khẳng định một phục hồi backend không hề nói.
- Nêu **cả hai con số và gán nhãn cả hai**: "6 NKD_NIGHT slots failed" + "6 STILL OPEN"
  hoặc "ALL RECOVERED · stream resumed at NKD_NIGHT_0230".
- Kết quả: bằng chứng từ **1285px → 241px**, cách chính câu phán quyết **63px**.
- Chỉ hiện khi có sự cố; 6 kịch bản còn lại không hiện thẻ.

### 3. Toàn bộ UI chuyển sang tiếng Anh
Chủ dự án chỉ ra trang đang lẫn tiếng Việt do các bản sửa trước của tôi. Đã đổi **cả chuỗi
hiển thị lẫn chú thích mã** trong 6 tệp của route này.
- Nhãn múi giờ dùng **HAN** cho khớp quy ước sẵn có (JST · HAN · YYC), không đặt tên mới.
- Phép kiểm: quét chữ đã render tìm dấu tiếng Việt, gồm cả nội dung sinh bởi `::before`/
  `::after`. **0 chỗ** trên cả 8 kịch bản. Đã thử phá: tiêm qua text node → 1, tiêm qua
  `content` CSS → 1, dọn xong → 0, nên phép kiểm đỏ được thật.
- `grep` toàn thư mục: không tệp nào còn ký tự tiếng Việt.

### Lỗi tự gây, bắt bằng đo
Thẻ bằng chứng thiếu `order` nên rơi vào nhóm mặc định cùng khối số liệu và render **dưới**
nó (241px lẽ ra thành 441px). Trong một nhóm `order`, thứ tự DOM mới quyết định.

### Đo cuối (kịch bản 6 slot hỏng — kịch bản nhiều nội dung nhất)
1440px và 390px: đè chữ **0** · cắt cụt **0** · nội dung mất **0** · tiếng Việt **0**.
Tám kịch bản: **8/8** khớp trạng thái dự đoán. Bộ tự kiểm route **7/7**. Test **198 passed**.

### Files touched
global_index/dash/realtime-next/{index.html, next.css, next.js, preview.html,
preview-states.js, preview.css}

---
## Sub-task: Hai biến thể thị giác A/B để chọn hướng (2026-08-16)
Status: CHỜ CHỦ DỰ ÁN CHỌN

### Đã dựng
`skin-a.css` (A · refined terminal) và `skin-b.css` (B · modern console), nạp chồng lên
next.css nên **cấu trúc đem so là y hệt nhau**, chỉ khác lớp thị giác. Chuyển qua lại bằng
`?skin=base|a|b` hoặc bấm hàng nút thứ hai trên dải vàng.
- **A** — giữ DNA tối/mono, nhịp 8px, chiều sâu bằng bậc nền thay vì viền 1px.
- **B** — thẻ bo góc có khoảng cách, nền phân tầng, sans cho tiêu đề/câu văn.
- Cả hai áp **luật tách kênh màu** đã thống nhất: màu số liệu hạ bão hoà, màu trạng thái
  giữ rực và không bao giờ dùng cho một con số. Lý do đo được: xanh lá đang sơn cho mức
  thay đổi vốn, regime, ngày SPY, UPL, lãi đã thực hiện và cả chấm trạng thái — sáu việc
  không liên quan, một màu.

### Phép kiểm mới: tràn khỏi THẺ (khác tràn khỏi khung nhìn)
Skin B có viền và khoảng cách nên tràn khỏi thẻ mới thành lỗi nhìn thấy được. Thêm phép
kiểm thứ tư này bắt được 3 chỗ tràn **có sẵn trên `/realtime`**: Broker acct +52px,
Paper reconcile +155px, HMM fit +19px — cả ba đều đã sửa trên route mới từ trước.

### Ba lần phép đo của chính tôi sai, phải rút lại
1. **So với mép PADDING thay vì mép THẺ** → báo 4 chỗ tràn giả (`$50,000`, `Protection`,
   `1 covered`, `39 slots`). Danh sách nhật ký cố ý có lề âm để trải sát mép thẻ, nên nó
   luôn "vượt" mép padding. **Đã lỡ sửa theo số giả** — hạ cỡ chữ ô Protection từ 21px
   xuống 16px — và đã RÚT LẠI, ghi chú lý do ngay tại chỗ.
2. **Phép kiểm thẻ thiếu miễn trừ khối cuộn.** Cột `ID`/`#288` của bảng Lệnh bị báo tràn
   59px, thực ra nằm trong `.table-wrap` (scrollW 506 > clientW 446) nên tới được.
3. **Đo hình học qua 12–18 iframe song song cho kết quả ảo** — báo skin A có 4 chỗ đè chữ
   và 1 chỗ cắt cụt; đo trực tiếp trên trang thì **sạch hoàn toàn**. Khung chưa render
   xong đã bị đọc. Từ giờ: iframe chỉ dùng để đọc trạng thái đã ổn định (lớp CSS), không
   dùng để đo hình học hàng loạt.

### Lỗi thật tìm ra khi dựng skin
`<link>` chèn từ script trong `<head>` nằm **trước** các stylesheet tĩnh, vì `appendChild`
chỉ thấy phần head đã parse tới đó — nên luật của skin thua nền ở cùng độ đặc hiệu mà
không có dấu hiệu gì. Sửa bằng thẻ giữ chỗ `<link id="skinLink">` đặt cuối `<head>`.

### Đo cuối (đo TRỰC TIẾP trên trang, kịch bản 6 slot hỏng, 1440px)
| | đè chữ | cắt cụt | tràn thẻ | tiếng Việt |
|---|---|---|---|---|
| base | 0 | 0 | 0 | 0 |
| skin A | 0 | 0 | 0 | 0 |
| skin B | 0 | 0 | 0 (2 chỗ là bảng cuộn, tới được) | 0 |

### Chờ quyết định
Chọn A hay B (hoặc ghép) → mới viết spec hệ thiết kế (token + thành phần) rồi tới bố cục.

### Files touched
global_index/dash/realtime-next/{skin-a.css, skin-b.css, preview.html, preview-states.js,
preview.css, next.css}

---
## Sub-task: Hai hướng thị giác nữa — C bento, D HUD (2026-08-16)
Status: CHỜ CHỌN

Chủ dự án bác cả A lẫn B ("vẫn xấu"). Quan sát đáng ghi: **A và B đều chỉ đổi lớp sơn** —
cả hai giữ nguyên dải 5 ô số liệu bằng nhau và các băng ngang. Nếu cái xấu nằm ở cấu trúc
thì đổi màu bao nhiêu lần cũng vậy.

Hướng lấy từ database của skill (đã loại pixel-art, Memphis, neumorphism, biomimetic,
cyberpunk vì sai bối cảnh). Chủ dự án chọn dựng C và D.

- **C · bento** (`skin-c.css`) — hướng DUY NHẤT đổi cấu trúc. Lưới 4 cột, thẻ chiếm 1–2 cột
  theo tầm quan trọng: hàng 1 EQUITY(2) + PERFORMANCE(2), hàng 2 MODEL(2) + RISK(1) +
  EXPOSURE(1). Mọi span dùng `minmax(0, …)` để một giá trị dài co chữ chứ không đẩy cột.
- **D · HUD** (`skin-d.css`) — nền đen, đường cyan mảnh, dấu ngoặc kỹ thuật ở góc thẻ (vẽ
  bằng pseudo-element, không thêm nút nào). Cố ý kiềm chế: không scanline, không glitch,
  phát sáng CHỈ áp cho dấu trạng thái, không bao giờ cho chữ hay số. Cyan dùng cho CẤU TRÚC
  nên không mang nghĩa, không lẫn với trạng thái. Đây là hướng duy nhất cố ý bỏ E4
  (tách sans) vì diện mạo phụ thuộc vào mono toàn phần.

### Lỗi bắt được khi dựng
**C hạ tương phản mạnh: 96/373 nút chữ dưới AA** (base 19). Thẻ của C sáng hơn nền cũ, mà
`--dim`/`--muted` vẫn giữ giá trị chỉnh cho nền tối nên khoảng cách thu lại. Nâng hai biến
→ còn **21/357**, ngang base. Ghi chú ngay trong tệp: hai biến này BUỘC vào `--surface`,
đổi nền thì phải đo lại.
**D cũng xấu hơn base về tương phản: 28 nút chữ** — chưa sửa, cần biết trước khi chọn.

### Đo trực tiếp trên trang (kịch bản 6 slot hỏng, 1440px)
| | đè chữ | cắt cụt | tràn thẻ | dưới AA |
|---|---|---|---|---|
| base | 0 | 0 | 0 | 19 |
| A | 0 | 0 | 0 | ~19 |
| B | 0 | 0 | 0 | ~19 |
| C (sau sửa) | 0 | 0 | 0 | 21 |
| D | 0 | 0 | 0 | 28 (chưa sửa) |

### Files touched
global_index/dash/realtime-next/{skin-c.css, skin-d.css, preview-states.js}

---
## Sub-task: Chốt hướng B, sửa bảng màu (2026-08-16)
Status: B đang là hướng được chọn; C giữ lại làm tham chiếu về kích thước

Chủ dự án xem lại và thấy **B · modern console** hợp hơn C, chỉ cần sửa màu.
(Trước đó C đã được siết kích thước theo yêu cầu — xem mục trên. Công đó không mất:
thang chữ 4 bậc và luật "ô cao theo nội dung" áp được sang B.)

### Bốn phát hiện về màu của B, và cái gốc rễ
1. **Mọi màu trung tính đều cùng hue 212.** bg, surface, panel, line, text, muted, dim —
   tất cả xanh lam. Không có màu trung tính thật nào.
2. **Hệ quả nặng nhất: `--blue` cũng hue 212** — màu nhấn cùng hue với chữ VÀ với nền, nên
   không thể đọc ra như một màu nhấn. Nó chỉ là "xám hơi khác".
3. `--bright` là **trắng tinh #ffffff**, chói trên nền tối.
4. `status-ok` vs `status-warn` chỉ **lệch 5 mức xám** — mất màu là thành một.

### Sửa gốc rễ chứ không sửa từng màu nhấn
Hạ độ lệch màu của nền thay vì chỉnh accent. Chroma (max−min kênh) của nền: `--bg`
13 → **7**, `--surface` 19 → **10**. Nền hết nhuộm thì mọi accent tự tách ra.
- `--blue` chuyển hue 206, bão hoà 63% → giờ đọc ra là xanh lam thật.
- `--bright` #ffffff → #f4f7fa.
- ok/warn tách thang xám: **5 → 48 mức**.

### Ghi chú về phép đo
Dùng "HSL saturation" để đánh giá độ trung tính của màu RẤT TỐI là sai — mẫu số
`1-|2L-1|` làm một màu gần đen như `#0b0e12` hiện 24% dù chênh lệch kênh chỉ 7/255.
Với màu tối phải đo **chroma**, không đo HSL saturation.

### Đo sau khi sửa (kịch bản 6 slot hỏng, 1440px)
đè chữ **0** · cắt cụt **0** · dưới AA **21/357** · tách thang xám ok↔warn **48 mức**.

### Việc tiếp
- [ ] Áp thang chữ 4 bậc + luật ô-cao-theo-nội-dung (đã làm ở C) sang B.
- [ ] Rồi mới viết spec hệ thiết kế.

### Files touched
global_index/dash/realtime-next/skin-b.css

---
## Sub-task: Bỏ luật hạ bão hoà + tự host webfont (2026-08-16)
Status: DONE

### Rút lại luật của chính tôi
Chủ dự án phản ứng hai lần với cùng một thứ: "không muốn đơn sắc", rồi "màu nhờ nhờ".
Thủ phạm là **luật tách kênh bằng ĐỘ BÃO HOÀ** do tôi đặt — hạ màu số liệu xuống 32-45%
để màu trạng thái nổi lên. Mà số liệu là phần lớn nội dung trang, nên hạ chúng = làm cả
trang xỉn.

Đã trả màu số liệu về đủ độ (`#35d68a`, `#ff5d6a`, `#4da6ff`, `#a98bff`). Trạng thái vẫn
tách được, nhưng bằng **HÌNH THỨC** thay vì độ bão hoà: chip có nền đặc, hình dạng riêng,
nhãn chữ. Hình thức vốn là kênh bền hơn — nó sống sót qua thang xám, màn hình kém và mù
màu, những thứ mà chênh lệch bão hoà đều không sống nổi.

### Tự host webfont
Máy chỉ có Cascadia Mono/Code, Consolas, Lucida Console, Courier New, Segoe UI, Arial.
**Hai lựa chọn trong bộ chọn font của trang thật là chết**: `JetBrains Mono` và
`IBM Plex Mono` không cài, chọn vào thì âm thầm rơi về Cascadia. Lỗi có sẵn, không phải
do route mới.

Tải về tự host (SIL OFL, cho phép phân phối lại): JetBrains Mono cho mọi con số, Inter cho
văn xuôi. Đặt ở `global_index/dash/fonts/`, phục vụ qua route `/dash/<path>` sẵn có →
**không có URL ngoài**, nên luật `assert "https://" not in source` vẫn nguyên.

**Bẫy đã mắc:** lần tải đầu ra 7 tệp, 287 KB — và cả 7 có kích thước trùng khít theo họ.
Hash ra giống hệt nhau: Google phục vụ **variable font**, một tệp phủ cả trục cân nặng.
Sửa thành khử trùng theo hash + khai báo `font-weight` dạng dải → **2 tệp, 80 KB**.
Script `scratchpad/fetch_fonts.py` giữ lại ghi chú này để không ai chia lại theo cân nặng.

### Đo
Font đã nạp thật (`document.fonts` báo `loaded`, và phép đo bề rộng xác nhận không rơi
fallback). Test **202 passed**. Không tệp mới nào chứa URL ngoài.

### Files touched
global_index/dash/fonts/{fonts.css, jetbrains-mono.woff2, inter.woff2} (mới),
global_index/dash/realtime-next/{skin-b.css, index.html, preview.html}

---
## Sub-task: Sửa font lộn xộn + padding lệch (2026-08-16)
Status: DONE

Chủ dự án báo "font lộn xộn" và "padding không chuẩn ở nhiều card". Đo ra **cả hai đều do
bản sửa của tôi**, không phải có sẵn:

| | base | skin-b (trước) | skin-b (sau) |
|---|---|---|---|
| Mép chữ trái của các thẻ | 24 · 26 · 28 (lệch 4px) | 21 · 39 · 41 (lệch **20px**) | **39** (thống nhất) |
| Số giá trị padding ngang | — | 4 (0/18/20) | **1** (18px) |
| Họ chữ | 1 | 2, không có luật | 2, **có luật** |

### Padding
skin-b thêm padding cho tiles và bands, nhưng `.section-band` không có padding ngang riêng
(tiêu đề của nó dựa vào băng), nên các tiêu đề mục đứng nguyên ở 21 trong khi mọi thứ khác
dịch vào 39 — cả cột trái so le. Đặt một biến `--pad-x: 18px` cho mọi khối cấp thẻ, và
xoá padding ngang của khối con để không thụt hai lần.
Hai mép còn lại (64, 108) là thụt lề CÓ CHỦ ĐÍCH: hình dạng của thẻ bằng chứng, và dấu
trạng thái + nhãn OK/FAIL.

### Font
Ranh giới sans/mono cũ không đọc ra được: "Paper Equity" sans nhưng "Problem" mono; tiêu đề
mục sans nhưng thanh điều hướng mono. **Hai họ dùng không có luật đọc ra lộn xộn hơn một họ
dùng nhất quán** — đúng thứ base đang làm.
Luật mới, mặc định là sans rồi kể tên dữ liệu ra:
- **SANS** mọi thứ là NGÔN NGỮ — thương hiệu, điều hướng, tiêu đề, nhãn trường, câu văn.
- **MONO** mọi thứ là DỮ LIỆU — số, giá, mã hợp đồng, mã lệnh, mốc thời gian, dòng log.
Đặt mặc định sans vì một nhãn lọt lưới chỉ hơi lệch, còn một con số lọt lưới thì phá thẳng
sự thẳng cột.

### Đo
đè chữ **0** · cắt cụt **0** · padding ngang **1 giá trị** · mép chữ trái **1 giá trị**.

### Files touched
global_index/dash/realtime-next/skin-b.css

---
## Sub-task: Về một họ chữ + bộ chuyển font (2026-08-16)
Status: CHỜ CHỌN FONT

Chủ dự án bác sans ở header, rồi bác luôn Inter. Phải nói thẳng: lý do tôi đưa sans vào là
câu *"mono 11-13px đọc lâu mệt hơn sans"* — **tôi khẳng định chứ chưa hề đo** trong phiên
này. Không đứng vững, nên bỏ.

- Về **một họ chữ duy nhất** (357/357 nút). Giữ token `--sans` trỏ vào stack mono thay vì
  xoá, để tách lại được bằng một dòng NẾU sau này thật sự đo.
- Ngoại lệ đã ghi trong tệp: **wordmark và thanh điều hướng không thuộc bên nào** của cặp
  ngôn ngữ/dữ liệu — chúng là nhận diện sản phẩm, quét vào sans là mất chất terminal.

### Bộ chuyển font trên trang xem
Tải thêm 5 mono (SIL OFL) → **9 tệp / 191 KB**, tự host nên vẫn không có URL ngoài.
`?font=` + hàng nút thứ ba trên dải vàng: JetBrains · Cascadia · IBM Plex · Roboto ·
Space · Azeret · Red Hat.

### Lặp lại đúng lỗi của chính mình
Chèn `<style>` từ script trong `<head>` để đổi `--mono` → **không ăn**: `appendChild` chỉ
thấy phần head đã parse tới đó nên style nằm TRƯỚC các stylesheet tĩnh và thua `skin-b.css`
ở cùng độ đặc hiệu — đúng cái bẫy đã mắc với `<link>` của skin ở lượt trước. Sửa bằng
**style nội tuyến trên phần tử gốc**, thứ luôn thắng stylesheet nên không bị thứ tự nạp
đánh bại.

### Đo
Mỗi lựa chọn font: 1 họ chữ trên toàn trang, `document.fonts` báo loaded, đè chữ **0**,
cắt cụt **0**.

### Files touched
global_index/dash/fonts/* (9 woff2 + fonts.css),
global_index/dash/realtime-next/{skin-b.css, preview-states.js}

---
## Sub-task: Thu gọn 3 dải trên, sửa HMM fit + padding, mở rộng bộ font (2026-08-16)
Status: CHỜ CHỌN FONT

Chủ dự án gửi ảnh chụp chỉ ra hai chỗ padding lỗi, cộng ba yêu cầu.

### 1. Ba dải trên: 176px → **149px**
Bớt padding và cỡ chữ, không bỏ nội dung nào. Phán quyết vẫn là chữ lớn nhất trang.

### 2. HMM fit: 3 dòng → **1 dòng**
Chủ dự án đề nghị thu nhỏ chữ, nhưng **thu nhỏ chữ một mình không giải quyết được**: cột
giá trị chỉ rộng 122px, mà chuỗi là 24 ký tự → muốn một dòng cần cỡ chữ **~8,5px**, quá nhỏ
để đọc. Phải cho nhãn xuống dòng riêng để giá trị dùng trọn 227px của ô; khi đó 15px vừa
đúng một dòng (đo lại: cao 20px, rộng 190px).

### 3. Padding trong ảnh chụp
- **Nhật ký**: mỗi `.job-row` có `margin: 0 -10px` riêng cho vệt bôi đậm khi rê chuột. Lượt
  trước tôi mới kéo `<ol>` vào, chưa kéo từng hàng — chữ vẫn thò ra ngoài padding **7px**.
  Kéo cả hai tầng → giờ nằm trong 3px.
- **Dòng nguồn của tiêu đề mục** là `nowrap` + ellipsis nên rụng ký tự khi thẻ hẹp lại
  (`2026-08-14 /` trong ảnh). Cho xuống dòng — cùng họ với luật "không cắt cụt giá trị".
- `Today's Decision`: đo ra **0 vi phạm padding**; chỗ trông lỗi là dòng nguồn bị cắt ở trên.

### 4. Bộ font: 7 → **15 lựa chọn**
Thêm Spline Sans · Intel One · Sometype · Kode · Martian · Geist · Fragment · Source Code.
17 tệp / 375 KB, tự host, vẫn không có URL ngoài.

### Đo (skin B, kịch bản 6 slot hỏng, 1440px)
đè chữ **0** · cắt cụt **0** · 1 họ chữ toàn trang · ba dải **149px** · HMM fit **1 dòng**.

### Files touched
global_index/dash/fonts/* (17 woff2 + fonts.css),
global_index/dash/realtime-next/{skin-b.css, preview-states.js}

---
## Sub-task: Sửa lại padding nhật ký, bỏ dải cửa sổ, dời Now Monitor (2026-08-16)
Status: DONE

### Bản "sửa padding" trước đó làm hỏng thêm — lỗi CHỌN SAI MỐC ĐO
Tôi xoá luôn `padding: 10px 10px 10px 17px` của `.job-trigger` cùng với lề âm của hàng.
Phép đo của tôi so chữ với **vùng trong của THẺ** và báo cải thiện (thò ra 7px → vào trong
3px), nhưng thứ mắt nhìn là khoảng cách giữa chữ và **vạch màu trạng thái của chính hàng
đó** — cái đó từ 17px về 0, nên trông sát viền hơn hẳn.
Đã trả padding về, chỉ triệt lề âm. Ghi chú lý do tại chỗ.

Thêm: dòng gộp `.journal-message` là con TRỰC TIẾP của hàng nên không hưởng padding của
`.job-trigger` — chữ ở 2px trong khi mọi thứ khác ở 19px. Cho cùng mốc 17px.

### Lại một lỗi đo nữa
Sau khi sửa, phép kiểm vẫn báo "2px" — vì `getBoundingClientRect()` trả **hộp viền** của
phần tử khối, không phải vị trí chữ. Đo lại bằng `Range.getBoundingClientRect()` trên chính
nút văn bản → mọi chữ trong hàng đều ở **19px** (26px là nhãn trong huy hiệu, có padding
riêng, đúng).

### Ba dải trên: 176px → **115px**
Bỏ dải "next entry window" theo yêu cầu. **Ẩn chứ không xoá**: next.js vẫn dựng và cập nhật
nó, phần tử giữ nguyên id. Xoá khỏi trang là thứ lớp này tuyệt đối không được làm.

### Now Monitor lên dưới dải phán quyết
Nó ở `.primary-column` còn dải ở `.overview-header` — hai container khác nhau nên `order`
không với qua được. **Dời nút thật** bằng next.js, mọi id đi theo (`getElementById` không
quan tâm vị trí trong cây). Đặt sau thẻ bằng chứng khi có sự cố để phán quyết và bằng chứng
của nó còn dính nhau; ngày sạch thì không có thẻ đó nên nó nằm thẳng dưới dải.
Kiểm sau khi dời: 6/6 id còn nguyên, `#nowScheduleFacts` vẫn được realtime.js ghi vào.
Ranh giới "▽ dưới đây là chi tiết để điều tra" chuyển sang mục Today's Decision.

### Bộ font: 15 lựa chọn (17 tệp / 375 KB, tự host)

### Đo cuối
đè chữ **0** · cắt cụt **0** · mép chữ nhật ký **1 giá trị** · ba dải trên **115px**.

### Files touched
global_index/dash/realtime-next/{skin-b.css, next.css, next.js, preview-states.js},
global_index/dash/fonts/*

---
## Sub-task: Bỏ lồng thẻ, cân lại chiều cao 5 ô số liệu (2026-08-16)
Status: DONE

### Chiều cao ô — đo ra khác điều tưởng
Chủ dự án nói Model Inputs cao hơn hẳn. Đo: **cả 5 ô đều đúng 246px** — chúng đã bằng nhau.
Vấn đề là NỘI DUNG: Model Inputs 217px còn Exposure 92px, nên Model Inputs là ô kéo cả
hàng cao lên và bốn ô kia trông rỗng.

Sửa: lưới 5 cột bằng nhau → **6 cột**, Model Inputs chiếm 2 cột và xếp nội dung 2-up.
Không thu nhỏ chữ (đã đo ở lượt trước: muốn HMM fit một dòng trong cột 122px cần cỡ ~8,5px).

| | trước | sau |
|---|---|---|
| Cao hàng | 246px | **178px** |
| Nội dung Model Inputs | 217px | **126px** |
| Ô kéo chiều cao | Model Inputs | Paper Equity (148px) |
| HMM fit | 1 dòng | 1 dòng (giữ) |

Exposure vẫn trống 38% — nó chỉ có 3 giá trị trên một hàng nên vốn ngắn. Chưa đụng.

### Lồng thẻ: 5 chỗ sâu 3 tầng → **1**
Cho `.section-band` viền + nền đã biến mọi hộp sẵn có bên trong thành thẻ-trong-thẻ: ô lịch,
hàng danh sách sự cố, khối chi tiết sự cố đều có khung riêng — một sự cố được vẽ trong ba
hộp lồng nhau. Băng giữ khung (nó là thứ tách khỏi trang), bên trong tách bằng KHOẢNG CÁCH
và một đường kẻ. Riêng hàng đang chọn giữ dấu, nhưng bằng vạch mép trái chứ không phải hộp.

### Đo cuối
đè chữ **0** · cắt cụt **0** · lồng thẻ sâu ≥3 tầng: **1** (một nút bấm).

### Cần chú ý
Now Monitor đã dời lên đầu, nên vào ngày có 6 sự cố nó đẩy toàn bộ khối số liệu xuống dưới
nếp gấp. Ngày sạch thì không sao. Chưa quyết có nên giới hạn số hàng hiển thị hay không.

### Files touched
global_index/dash/realtime-next/skin-b.css

### Skin E — khớp với bản dựng tham chiếu (2026-08-17)

Bản dựng "Ops Dashboard.html" là hiện thực đầy đủ của spec chữ đã dùng để viết
`skin-e.css`. Bảng màu 24 giá trị đã trùng sẵn; cái thiếu là những chi tiết
spec chữ không nói. Đã thêm vào `skin-e.css`:

- vạch nhấn 3×15px trước mỗi tiêu đề mục, màu theo miền (tiền / runner / rủi ro)
- viền trên 2px màu riêng cho từng ô Now Monitor
- nền chuyển sắc cho thẻ Paper Equity và Model Inputs; số lớn 40px
- dải phán quyết chuyển sắc theo trạng thái (`:has()`), ba biến thể ok/watch/bad
- cột nhật ký 452px, nền tối hơn trang một bậc
- chấm live thở 2.4s thay vì nhấp nháy

Ba lỗi bố cục sửa kèm (đo được, không phải thẩm mỹ):
- `.performance-zone .zone-grid` là lưới 2 cột **gap 0** → hai số dính nhau; đổi
  thành mỗi số một dòng, nhãn trái ↔ số phải. Exposure tương tự (3 cột 129px
  bóp "Protection / covered").
- Model Inputs chia 180px / 671px → "Calm" bị đẩy sát "SPY data"; đổi hai cột bằng nhau.
- `.header-dashboard` giữ 3 cột xuống tận 390px → thẻ equity rộng 105px, số chạy
  77px ra ngoài. Đóng khung lại dưới mốc 680px (mốc của `realtime.js:8`).

Đo sau khi sửa (1900 / 1440 / 390px, trạng thái breaker):
chữ đè chữ 0 · chữ vượt viền thẻ 0 · cắt cụt ngoài ý đồ 0 · tràn trang 0 ·
màu ngoài bảng 24 giá trị: 0 · URL ngoài: 0.
`git diff --stat -- global_index/dash/realtime/` rỗng — trang production chưa bị đụng.

### Còn treo
- [ ] Chưa chốt hướng cuối giữa B (đã tinh chỉnh ~15 vòng) và E (theo bản dựng)
- [ ] 19–21 node còn dưới AA — chưa truy nguồn
- [ ] Chưa có test ghim bất biến của route mới (kể cả phép đo chữ-đè-chữ đã sửa)
- [ ] Chưa commit gì

### Vòng 2 — khớp CÁCH XẾP CHỮ, không chỉ màu (2026-08-17)

Phản hồi "sao ko giống tí nào" là đúng: vòng 1 chỉ đổi màu/viền/khoảng cách, mà
diện mạo bản dựng nằm ở chỗ nhãn đứng đâu so với con số. Đã sửa, toàn bộ bằng
CSS trên markup sẵn có — không viết lại chuỗi nào:

- nhãn dòng thôi viết hoa (`Open UPL`, `Regime` — DOM vốn đã là chữ thường,
  chỉ bị `text-transform` ép hoa)
- Model Inputs: nhãn **trên**, giá trị **dưới**, hai cột đều nhau
- Performance / Exposure: quay lại lưới **2×2** có rãnh thật (vòng 1 tôi đổi
  thành 4 dòng dọc — sai hướng, đã gỡ)
- Risk: mức trần lên cùng dòng tiêu đề, thanh đo xuống đáy thẻ
  (dùng `display: contents` để tách hai `span` trong một `<small>` ra hai hàng
  lưới — không dời node)
- ô Now Monitor: 3 dòng, `04:20 ET` ↔ `in 1h 23m` cùng dòng cuối
- một vạch liền trên dãy ô, thay cho bốn màu rời
- dòng broker thành chân thẻ có kẻ ngăn, `Paper reconcile` đẩy phải
- `.header-dashboard` sang lưới **6 cột**: hàng trên hai nửa, hàng dưới ba phần ba
  (lưới 3 cột cũ không diễn đạt được hai tỉ lệ khác nhau)

**Lỗi trong khung xem thử, đã sửa:** bộ chọn phông gán stack mono vào cả `--sans`
và `--font-ui`. Đúng cho skin B (cố ý một họ chữ) nhưng âm thầm dí mọi skin khác
về mono — kể cả E, vốn dựng trên cặp sans-cho-chữ / mono-cho-số. Giờ chỉ đổi
`--mono`; skin nào muốn một họ thì tự khai `--sans: var(--mono)` như B.

Đo lại 1900 / 390px: chữ đè chữ 0 · vượt viền thẻ 0 · tràn trang 0 ·
họ chữ đang dùng: đúng 2 (Mono 321 node / Sans 86 node) ·
màu ngoài bảng 24 giá trị: 0 · production `/realtime` chưa đụng.

---

## Task: Rà soát vòng 2 các bản sửa runner futures — 16–17/8
Status: DONE (còn 1 mục chặn bởi dữ liệu)
Phạm vi tệp: `global_index/runner.py` · `ibkr_broker.py` · `broker.py` · `run_scheduler.py` ·
`monitor/backend/open_issue_reader.py` · `ibkr_reader.py` · `dash/realtime/realtime.js` +
các tệp kiểm tương ứng. KHÔNG chạm `monitor/backend/app.py` (phiên song song).

### Completed
- [x] Rà 26 mục khai đã đóng: **19 xác nhận đóng · 4 đóng một phần · 1 tiền đề sai · 2 để lại**
- [x] Bảy chỗ hở mới → 6 đã đóng, 1 rút lại (không phải lỗi), 1 còn mở
- [x] Lỗi do chính đợt sửa trước tạo ra: phép kiểm tự đỏ vĩnh viễn từ 04/9 — đã tháo
- [x] Phát hiện tiến trình lập lịch chạy mã cũ hơn bản sửa 3 ngày; đã báo, đã restart
- [x] Suite: 848 → **874 xanh, 0 đỏ**; toàn bộ chênh lệch quy được về phép kiểm mới

### Còn mở
- [ ] **Ngưỡng đối soát $250** — cơ chế đúng, con số dựng trên sai đại lượng. Chặn bởi
      dữ liệu: dòng nhật ký mới (ghi phần sleeve book trong lượt) phải tích luỹ vài tuần.
- [ ] **Xác nhận `contract_month` thật sự được điền** — đêm 17/8 không lệnh vào nào nên
      chưa đo được. Đây là điều kiện để bản sửa cửa sổ ngày chuyển có tác dụng; nếu
      trường luôn rỗng thì nó rơi về hành vi cũ, **im lặng**. Dịp tới: slot Rổ 4 14:05 ET.
- [ ] Vùng chưa ai rà: đường phát lại bóng · khâu sinh tín hiệu · các panel ngoài hai tệp đã chạm.
- [ ] `STOP_REPAIR_0420 FAILED` (17/8) vẫn trên panel — chủ dự án chốt chưa đào.

### Cần làm khi tiện
- [ ] **Khởi động lại scheduler** — bản sửa nhịp tim + phạm vi khoá nằm trong `run_scheduler.py`,
      không có đường nạp lại. Không gấp.
- [ ] **Khởi động lại backend** — cảnh báo bảng lịch + hai tên trường mới là module Python.
      Không gấp: cảnh báo còn 95 ngày mới kêu.

### Key decisions
- Ngưỡng cảnh báo bảng lịch chuyển hợp đồng = **14 ngày** (chủ dự án chốt). Kêu lần đầu
  20/11/2026. An toàn vì mốc nó đếm ngược tới không phải vách đá — tháng cuối vẫn giao
  dịch trọn quý sau đó, tới tháng 3/2027.
- **Bỏ gom dòng trong job view** (chủ dự án chốt): một dòng mỗi lần chạy.
- **`MAX_HOLD` cố ý KHÔNG vào khoá chống chạy chồng** — không đường nào khác thực hiện
  lệnh đóng theo hạn, nên bỏ lỡ nó tệ hơn va chạm mà khoá ngăn. Có phép kiểm ghim quyết định.
- **Lệnh vào vẫn lấy tháng theo lịch**, chỉ lệnh ra và stop mới hỏi sổ — vị thế mới thuộc
  về tháng đang giao dịch.

### Files touched
RUNNER_AUDIT_ROUND2.md (báo cáo, mục 11 = trạng thái sửa) · 6 tệp mã · 8 tệp kiểm
Commit: `8a09ced` `dceed72` `e839d84` `0636f5b` `de14600` `46d15bd` `4e6216f`

### Skin E — port theo bản dựng thật (2026-08-17, tiếp)

Lấy được bản gốc `Dashboard 2A.dc.html` qua design MCP, dựng thành trang chạy
được tại `global_index/dash/realtime-next/reference.html` (mở loop template, đổi
Google Fonts sang font tự host). Từ đó mới đo được độ lệch thay vì nhận xét.

Năm cơ chế đã chặn việc "làm cho giống", đều bắt bằng đo:
- `.header-zone { min-height: 152px }` ghim thẻ stats cao gấp ~1.5 lần nội dung
- `.model-inputs-zone.watch::after` vẽ dải 2px hổ phách — pseudo-element nên mọi
  phép đo `border` đều báo sạch
- `.positive/.negative/.warning { color: var(--x) !important }` → phải đè bằng
  chính biến, không đè bằng selector; lộ ra xanh nền `#36bf69` vs gốc `#3ecf8e`
- ba khối CSS viết cho tên lớp không tồn tại (`.journal-tabs`, `.job-note`,
  `.tag.runner`) — chạy mà không chạm phần tử nào, không báo lỗi
- `.open-issues-shell` là `<details>`, lưới list/detail thật ở `.open-issues-layout`

Đo sau khi sửa, 1900px và 390px: chữ đè chữ 0 · vượt viền thẻ 0 · tràn trang 0 ·
11/11 điểm màu mốc khớp bản gốc · thẻ stats 98–107px (gốc 103px), equity 186px
(gốc 182px). Trang production `git diff` rỗng. Chưa commit.

### Skin E — bổ sung dữ liệu + bố cục (2026-08-17, tiếp)

- Thanh nhấn hàng issue và viền trên khung chi tiết dùng chung `#5b9cf0`
- Model Inputs: thêm **Fit end** (`model_age.model_name`) và **Re-freeze**
  (`refreeze.pending`); chuyển 2 cột → 3 cột × 2 hàng, chiều cao **168px không đổi**.
  Còn `regime_freshness.bday_stale` chưa dùng nếu muốn thêm.
- Exposure: thêm **Gross** = tổng `cluster_exposure[*].gross_pct`
- Cột nhật ký trải hết chiều cao trang (đáy 1779 = đáy main); danh sách giữ khung
  cuộn một màn hình — để danh sách quyết chiều cao thì trang phình lên 7801px
- `next.js` nay đọc thêm `/api/v1/runner-state`; đọc hỏng → mọi ô mới về `--`,
  không bao giờ giữ lại giá trị của lượt trước

Đo 1900px và 390px: chữ đè chữ 0 · chữ vượt thẻ 0 · tràn trang 0 · test 265 passed.

### Cảnh báo phối hợp
Phiên khác đang sửa `global_index/dash/realtime/realtime.js`, `monitor/test_realtime_dom.py`,
`run_maxhold_exit.py`, `run_stop_repair.py`, `test_kill_switch.py` — cùng tuyến với phiên này.
`realtime-next/` và `dash/fonts/` của phiên này còn untracked: ai commit bằng `git add .`
sẽ quét trọn việc đang dở.

### Skin E nối vào trang thật (2026-08-17)

`index.html` (route `/realtime-next`) trước đó KHÔNG nạp skin nào — mọi thay đổi
chỉ hiện trong `preview.html?skin=e`. Đã thêm `<link ... skin-e.css>`; dòng đó
chính là chỗ chọn hướng B hay E, có ghi chú tại chỗ.

Đo lại trên chính `/realtime-next` (không phải preview):
- 1900px: 232 node văn bản · chữ đè chữ 0 · vượt thẻ 0 · tràn trang 0
- 390px: 586 node văn bản · chữ đè chữ 0 · tràn trang 0
- Open Issues: vạch trái thẻ = vạch trên khung chi tiết = `#5b9cf0`
- Now Monitor: khung chi tiết `#5b9cf0`; chưa có sự cố nào trong dữ liệu live nên
  CHƯA đo được cặp này trên trang thật — dùng chung luật, đã khớp trong preview
- test 265 passed

### Bản E áp lên /realtime (2026-08-17)

Chỉ sửa `global_index/dash/realtime/index.html`. `realtime.css` và `realtime.js`
KHÔNG đụng — bốn dashboard còn lại dùng chung. Backup: `index.html.before-skin-e`;
gỡ ba dòng link/script trong <head> là trở lại như cũ.

Hai thứ phải sửa TRƯỚC khi áp, cả hai là lỗi của route mới:
- `#schedulerContext` bị thiếu trên /realtime-next. `realtime.js:377` có `if (spEl)`
  nên không sập, nó chỉ IM LẶNG ngừng báo: Scheduler DOWN / xN RUNNING / OLD CRON.
  Đã khôi phục.
- Bộ đổi font đã chết dưới skin E: skin khai `--mono` cứng, còn bộ đổi font điều
  khiển `--font-ui`. Đo: 5 lựa chọn → font render không đổi lần nào. Sửa bằng
  `--mono: var(--font-ui, ...)`. Đo lại: 5 lựa chọn → 5 họ chữ.

Hai test đỏ sau khi áp, đã sửa (KHÔNG sửa test):
- `test_frontend_modules_keep_data_boundaries` ghim nhãn "Working orders"; đã trả
  lại nhãn gốc (và "Realized today"). Nhãn của trang chính xác hơn bản dựng.
- `test_no_content_is_clipped_off_the_right_edge[390]` bắt hai tầng: luật
  `.header-live-context` của skin đè mất phần thu nhỏ header ở ≤680px
  (realtime.css:527-530); và `.table-wrap { overflow: hidden }` cắt bảng lệnh
  thay vì cho cuộn (bảng nền dùng `overflow: auto`).

Đo cuối trên /realtime: 265 passed · chữ đè chữ 0 · tràn trang 0 · console sạch ·
bộ đổi font 5/5 · Model Inputs 6 ô / 3 cột / 2 hàng · ba thẻ figure 107 bằng nhau.

---

## Sub-task: Rà soát độc lập hướng cổ phiếu — CHỈ ĐỌC (2026-08-17)
Status: DONE
Phạm vi tệp: chỉ ĐỌC (`raits/**`, `docs/stocks/**`, báo cáo nghiên cứu ở thư mục gốc).
Ghi duy nhất: `STOCKS_AUDIT_2026-08-17.md` (mới) + mục này. KHÔNG chạm futures, KHÔNG commit.

### Đã làm
- [x] Đo lại nền cổ phiếu từ artifact trên đĩa (không chép số từ tài liệu cũ)
- [x] Đối chiếu tài liệu trạng thái (06/07) với bằng chứng bootstrap 08/07 + OOS 09/07
- [x] Đọc lại 6 báo cáo nghiên cứu 09-11/08 và đối chiếu với tiêu chí loại tự cam kết
- [x] So futures/cổ phiếu trên đúng cùng khoảng 2018-2022, cùng nền vốn $50k

### Phát hiện chính
- Ba con số vẫn gọi chung là "IS baseline" do BA cấu hình khác nhau sinh ra
  (bộ quét bật/tắt, PDT tắt/bật, chạy từng năm/chạy liên tục). Toàn bộ verdict
  "chiến lược nào có edge" đo trên cấu hình KHÔNG phải cấu hình sản xuất.
- Chưa từng có con số nào vừa đúng cấu hình sản xuất vừa chạy liên tục nhiều năm.
- OOS 2023-2024: bỏ 5 lệnh trên 430 thì còn $261/$6.666; không chiến lược nào đạt ngưỡng.
- Hệ cổ phiếu đứng yên từ 10/07 (mã) / 07/07 (ảnh chụp); không có việc nào chạy theo lịch.
- 6 phép sàng tháng 8 đều âm; cái duy nhất có tín hiệu thật (đảo chiều sau gap) mất
  10,6 điểm cơ bản trong 5 phút đầu — ngoài tầm với của nhịp 5 phút.
- Vault 2025 cho cổ phiếu CHƯA chạy được: không có dữ liệu 2025 (dữ liệu ngày dừng 2024-12-31).

### Đề xuất (chờ chủ dự án quyết)
- A: chốt hồ sơ + sửa tài liệu trạng thái cho khớp bằng chứng (~1 buổi)
- B: chạy MỘT lần liên tục 2017-2022 đúng cấu hình sản xuất, cam kết ngưỡng trước (~1 ngày máy)
- C: Vault 2025 — chỉ sau B, và cần tải dữ liệu 2025 + chạy lại WFO trước

### Files touched
STOCKS_AUDIT_2026-08-17.md (mới), TASK.md (mục này)

---

## Task: Mang giao diện /realtime sang /paper
Status: DONE (bước 1-3)

### Đã làm
- [x] Bước 1 — mốc so 5 dashboard × 2 viewport, bốn bẫy đo đóng ngay trong đầu đo
- [x] Bước 2 — tách bảng màu ra `shared/tokens.css`, nạp sau `realtime.css`
- [x] Bước 3 — `shared/components.css`: thẻ, bảng, tab, băng mục, dải phán quyết
- [x] Ghim bất biến: mọi luật trong sheet dùng chung phải thắng được trên trang thật
- [x] Mutation: tiêm lại luật chip đã gỡ → test đỏ đúng lý do → khôi phục, diff sạch

### Kết quả đo
- 4 tab × 2 viewport (1900/390): va chạm, cắt mép, tràn ngang, chữ dưới AA — 0→0
- Đầu đo chứng minh đỏ được: `.blocker-card{width:3000px}` → cắt mép 0→136 → gỡ → 0

### Quyết định
- KHÔNG ánh xạ chip trạng thái: chúng vốn đã là viền + chữ màu. Số "khối màu đặc"
  báo trước đó do bộ định dạng màu vứt alpha; alias sẽ xoá tín hiệu trạng thái.
- Không sửa `paper.js` (phiên khác giữ) → dùng luật alias, markup giữ nguyên.
- Tab con trong panel P&L để nguyên, giữ phân cấp với khay tab chính.

### Chưa xác minh được
- `.audit-panel` và `.audit-evidence-table` là lớp thật trong `paper.js`/`paper.css`
  nhưng payload hiện tại không sinh ra → alias chưa được nhìn thấy chạy.
- `/analytics` và `/reports` cố ý chưa nạp token; `/reports` còn ~26% chữ dưới AA.

### Files touched
global_index/dash/shared/components.css, global_index/dash/paper/index.html,
monitor/test_realtime_skin.py  (commit 365fd88)

### Bước 3b — lớp chữ (commit 2598b83)
Sau bước 3 người dùng vẫn thấy "hầu như không đổi". Đo hai trang cạnh nhau thì rõ:
viền/bo góc là cái khung, còn thứ mắt đọc là CHỮ, và chữ chưa đụng tới.
- realtime: phần lớn 400, trần 700, nền 11px. paper: 6 luật 900 + 23 luật 800, nền 10px.
- Sinh 42 luật phủ TỪ paper.css (brace-aware, không kéo luật @media ra ngoài).
- Ba họ: chip 9px/400 · nhãn in hoa 11px/500 · còn lại thang 700/600/500 + nền 11px.
- Kết quả: 900 và 800 biến mất; dải 11px 42 vs 50, 12px 46 vs 53, 9px 6 vs 14.
- Không hồi quy: 4 tab × 1900/390 vẫn 0 va chạm / 0 cắt mép / 0 tràn / 0 dưới AA.

### Còn khác (đo được, chưa làm)
- Độ đậm áp đảo: paper 500 (48 node) vs realtime 400 (123). Paper còn nặng hơn một bậc.
- Cỡ tiêu đề: paper 18/21px vs realtime 15/17px — cố ý giữ, là quyết định thiết kế.
- Bước giãn: paper dùng gap 3px 32 lần; realtime dùng 5/10/12/14px. Chưa đụng.

---

## Task: Rà soát vòng 2 runner futures — mở rộng thành sửa + quét theo họ lỗi
Status: DONE (phần code) · CHỜ NGƯỜI VẬN HÀNH (2 việc) · CHỜ DỮ LIỆU (3 việc)

### Completed
- [x] `RUNNER_AUDIT_ROUND2.md` — báo cáo vòng 2, mỗi mục một trong bốn phán quyết, cộng
      mục 12 (quét nốt ba vùng treo) và 12.4–12.5 (đã vá + hàng rào)
- [x] Vòng quét vào lệnh dưới chế độ nối tiếp: sạch, có đo, có đi qua nhánh
- [x] Trang bằng chứng giấy: 4 lỗi (`df908ed`) — sổ trống báo đỏ · nhánh giả ở thẻ chất
      lượng · "không so được" tính là "khớp" · trạng thái tổng xanh hơn thành phần
- [x] Nhãn `[BOOKED]`: một lần đóng vị thế không còn biến mất vì tiến trình thoát 0 (`c2a59ff`)
- [x] Đường dẫn thông tin xác thực Flex: runbook tách hai lối + thông điệp lỗi biết phân
      biệt "chưa đặt" với "đặt sai phạm vi" (`c2a59ff`)
- [x] Trần sao kê Flex: `flex_coverage`, `AWAITING_FLEX` không tính vào `unresolved` (`c2a59ff`)
- [x] Quét họ "rỗng đọc thành 0": 21 chỗ, vá 5 chỗ quyết định cổng + phép kiểm chặn tái
      phát (`defac12`)
- [x] Slot bị cắt ngang bởi khởi động lại ≠ slot không hề chạy (`4a84260`)
- [x] Suite 914 passed, 0 failed

### Chờ người vận hành
- [ ] **Khởi động lại backend** — `4a84260` và các thay đổi Python khác chưa sống; dòng
      "scheduler attention required" còn hiện tới khi đó
- [ ] Tránh khởi động lại **scheduler** gần các slot nối IBKR, nhất là 09:31 ET

### Chờ dữ liệu
- [ ] **Độ trễ công bố Flex** — phép đo đang chạy, ghi vào
      `<scratchpad>/flex_latency.log`. Cần chứng minh < 30,3h để job 22:20 ET dùng được.
      Cận dưới đã đo: > 10,1h. Mốc quyết định: 22:20 ET 18/8.
- [ ] **Dòng CLOSE của M2K 10/8** — cố ý KHÔNG dựng bằng tay: `+179.50` suy được từ
      chênh lệch equity, giá khớp thì không, và suy ngược từ P&L sẽ bịa ra lệch giá = 0
      ngay trong cổng chất lượng đang vỡ. Chờ sao kê broker.
- [ ] **Ngưỡng $250** — mọi quan sát vẫn `booked this run +0.00`

### Chưa quyết
- [ ] MAX_HOLD nằm ngoài mutex, không có dòng nào giải thích. Đánh đổi thật:
      `_run_guarded` **bỏ qua** chứ không xếp hàng, nên đưa vào mutex nghĩa là chấp nhận
      job đóng vị thế tới hạn có thể bị bỏ qua. Cần người quyết.
- [ ] `contract_month` vẫn chưa từng được điền trong đời thật (chưa có lệnh vào)

### Key decisions
- Không bịa dữ liệu để đóng một lỗi hiển thị: dòng M2K chờ bằng chứng broker
- Trần nguồn dữ liệu phải được **nói ra**, không phải báo như sự cố
- Im lặng luôn là báo động: slot không để lại dấu vết không được che bởi slot sau
- Vá một họ lỗi bằng một nguyên hàm + một phép kiểm chặn tái phát, không vá 21 chỗ lẻ

### Files touched
global_index/dash/paper/paper.js, global_index/run_scheduler.py, global_index/runner.py,
global_index/run_maxhold_exit.py, global_index/run_stop_repair.py, monitor/flex_pull.py,
monitor/paper_pnl_compare.py, monitor/backend/schedule_status.py,
docs/futures/IBKR_FLEX_SETUP.md, RUNNER_AUDIT_ROUND2.md,
monitor/test_paper_dom.py, monitor/test_flex_coverage.py, monitor/test_no_zero_for_missing.py,
monitor/test_dashboard_backend.py, global_index/test_run_echoes_critical.py,
global_index/test_session_report_slot.py, global_index/test_resume_equivalence.py

---

## Task: Kế hoạch chuyển hệ futures sang VPS Windows (2026-08-18)
Status: KẾ HOẠCH XONG — chờ chủ dự án chốt 3 mục

Tài liệu: docs/futures/VPS_DEPLOY_PLAN.md (mới)
Phạm vi tệp: chỉ ĐỌC toàn bộ mã. Ghi duy nhất: tài liệu trên + mục này. KHÔNG commit.

### Đã đo
- Paper mới 15/60 phiên; trade_log 18 OPEN + 10 CLOSE (cổng fill_quality đòi 100)
- 8/10 dòng CLOSE thiếu exit_reason -> cổng C1 nhánh STP (n=30) không thể đầy
- 44 lần khởi động scheduler trong 20 ngày; 203 job completed OK / 35 lần exited khác 0
- Dữ liệu phải mang: data/cache/futures 71 parquet = 2501 MB + global_index/data 178 MB
- Bề mặt Windows-only: monitor/ops.py 550 dòng + exercise_rollover_live.py
- Đã portable sẵn: runner.py _pid_alive (nhánh POSIX), flex_pull (guard sys.platform)
- 3 đường dẫn cứng D:\raits trong generate_replay_snapshots.py -> giữ ổ D: trên VPS
- Lịch APScheduler ET-native, đổi máy không đổi lịch

### Quyết định
- Chọn Windows VPS (chủ dự án, 18/8): monitor/ops.py chạy nguyên, IB Gateway như cũ.
  Đổi lại phải bịt việc Windows tự khởi động lại bằng cấu hình.
- Chuyển SỚM hơn thứ tự PAPER_ROUTE ghi: nếu chờ paper xong thì 60 phiên bằng chứng
  nằm trên máy A còn tiền thật chạy máy B chưa có mẫu nào.

### Chờ chủ dự án chốt
- [ ] Cấu hình VPS — chờ đo RAM đỉnh của slot 15:55/02:55 (shadow-verify)
- [ ] Số ngày đối soát song song 0 lệch trước khi chuyển (đề xuất 5)
- [ ] Chuyển khi đang có vị thế mở, hay chờ ngày phẳng

### Ràng buộc thời điểm
- KHÔNG đụng scheduler/backend trước 22:20 ET 18/8 (= 09:20 VN 19/8) — phép đo độ trễ
  Flex đang chạy, chốt ở mốc đó

### Files touched
docs/futures/VPS_DEPLOY_PLAN.md (mới), TASK.md (mục này)

### Bổ sung 18/8 — models/ bị thiếu trong bản kiểm kê đầu, đã đo lại và sửa
- models/hmm/ có 43 575 tệp .pkl (54,8 MB) + futures_freeze_registry.json (761 B)
- Nhánh futures KHÔNG nạp pickle nào: _validated_core.py:112 gọi eng.fit(..., save=False),
  không có lời gọi load_latest trong global_index/ futures/ monitor/
- Chỉ chép hai tệp JSON (freeze registry + refreeze_pending nếu có), bỏ 54,8 MB pickle
- 34 294/43 575 tệp (79%) sinh trong hai ngày 06-07/6 = dư của quét backtest, không phải vận hành
- Lệch phạm vi: raits/hmm/engine.py:368 load_latest() chọn theo mtime — nhánh cổ phiếu,
  đứng yên từ 10/7, không thuộc đợt chuyển; ghi lại phòng khi dựng lại trên VPS
- Đo thêm: raits/data/cache = 5,6 GB (nhánh cổ phiếu, KHÔNG thuộc đợt chuyển).
  Đợt chuyển là 2,7 GB, không phải chép cả d:\raits (8,3 GB).
  Sau khi chuyển, máy cũ là nơi DUY NHẤT giữ 5,6 GB đó (dựng lại 2-3h) -> chưa được bỏ máy cũ.
- Đã CHỨNG MINH bản kiểm kê 2,7 GB là đủ (không còn là giả định):
  repo có 123 033 parquet / 7 362 MB, 1 094 tệp nằm ngoài hai thư mục kiểm kê.
  run_live_day khai --data-dir và --nkd-parquet là required=True (không mặc định)
  -> phải đọc bên gọi. Liệt kê đủ 8 module scheduler bắn ra: không job nào chạm
  ra ngoài data/cache/futures + global_index/data + spy_daily_live.csv + live_positions.json.

---

## Sub-task: Có hướng nào trade trong regime Calm không? (futures) — 2026-08-18
Status: DONE — verdict: KHÔNG có hướng nào đủ bằng chứng; không đề xuất thay đổi production

### Đo được
- [x] Calm = **883/2167 ngày (40,7%)** theo nhãn production (spy_daily_live.csv, train 2018-01-01,
      n=3, fit_end 2024-12-31). IS 40,2% · vault 2025 45,2% · paper 2026 39,7%.
      Calm đi thành khối: trung vị 6 ngày/chuỗi, 93,9% ngày Calm nằm trong chuỗi ≥5 ngày.
      Vol trung vị: Calm 9,90% < Normal 15,45% < Stress 25,99% (self-check thứ tự PASS).
- [x] Toàn nhánh futures **không vào lệnh nào** trong Calm: swing Rổ 4 và NKD dùng chung
      `backtest_swing_tf` → cổng `allowed_regimes` lấy từ `raits/strategies/trend_follow.py`
      (['Normal','Stress'], chú thích "Section 6.1" = blueprint CỔ PHIẾU); STRESS_MID gác
      `today_regime == "Stress"`.
- [x] `futures/basket.py` REGIME["allowed_regimes"] **không được đọc ở bất kỳ đâu** — chỉ
      `hmm_fit_end` và `n_components` được dùng. Là mô tả chết, hiện trùng với hành vi thật.
- [x] Việc loại Calm là **tàn dư kế thừa, không phải kết quả đo trên futures**: `gate4_wfo.py`
      chỉ dựng khung 5 phút cho ngày thuộc regime allowed → Calm chưa bao giờ nằm trong
      không gian tìm kiếm WFO.
- [x] **TF chạy đúng luật hiện tại nhưng cho vào lệnh trong Calm** (ema30/mult2.5/hold5,
      14:00–15:55, 2-tick, 1 hợp đồng, không cap): 1.833 lệnh, **+$6.972, PF 1,14, exp $3,80**
      (production Normal+Stress: 2.496 lệnh, +$32.694, PF 1,30, exp $13,10).
      Mỏ neo: run_loop tái tạo TRÙNG KHÍT `backtest_swing_tf` trên cả 4 mã (615/618/644/619 lệnh,
      P&L khớp từng đồng) trước khi đọc nhánh Calm.
      **Tập trung, không phải quy luật**: 2024 đóng $6.041 (86,6%); MNQ đóng $6.424 (92,1%).
      Bỏ 2024 → +$931/1.516 lệnh ($0,61/lệnh). Bỏ MNQ → +$548/1.383 lệnh ($0,40/lệnh).
      2/7 năm âm (2019, 2021). Trượt cổng "mọi năm dương" của chính dự án.
      Kiểm chéo: 2022 chỉ có 5 ngày Calm → nhánh Calm cho 17 lệnh (trần 20 = 5×4). Khớp.
- [x] `orb_futures/overnight.py` (giữ qua đêm 15:55 → mở cửa hôm sau) — **lần đầu được chạy**:
      cost×2, Calm+Normal: 5.976 lệnh, PF 1,02, +$5.116, 2/7 năm âm (2022 −$10.585) → NO-GO.
      Chỉ Calm: 2.832 lệnh, PF 1,01, **+$513** ($0,18/lệnh), 3/7 năm âm → NO-GO.
      Nhạy chi phí quyết định: cost×1 cho +$20.743 nhưng cost×2 chỉ còn +$5.116 → biên gộp
      ≈$6,09/lệnh trong khi vòng phí 2-tick ≈$5,23/lệnh. Tương quan với swing TF +0,05 (Calm-only
      −0,00) — sẽ đa dạng hoá TỐT nếu có lãi, nhưng không có lãi.
- [x] Hai cơ chế còn lại đã đóng từ 2026-07-09 và **đã chạy KÈM ngày Calm** (mặc định
      `--allowed Calm,Normal`): ORB breakout 231 lệnh PF 0,67/0,63 (7/7 năm âm); Gap fill
      100 lệnh PF 0,64/0,58 (5/7 năm âm).

### Kết luận
Bốn cơ chế đã đo trên ngày Calm — momentum chiều chiều (TF), breakout mở cửa (ORB),
fade khoảng hở (gap fill), giữ qua đêm — **không cơ chế nào qua cổng**. Calm không phải chỗ
"chưa ai thử" nữa; nó là chỗ **đã thử bốn hướng và không hướng nào đứng vững**.
Không đề xuất mở Calm cho TF: con số dương chỉ đến từ một mã trong một năm.

### Chưa kiểm (đừng đọc là "đã quét hết")
- Mean-reversion nội phiên trong Calm bằng khung nhãn production (variance ratio) — script đã
  viết `scratch/calm_mr_probe.py`, CHƯA chạy. `mean_reversion_explore.py` bản gốc đo lệch khung
  (không truyền hmm_fit_end → fit tới 2019-06-30, khác production 2024-12-31).
- Lát cắt OOS 2025 cho nhánh Calm (dữ liệu frozen_2025_sim có sẵn).
- Đo chính xác phần P&L do vị thế mở từ Normal/Stress vắt qua ngày Calm.

### Files touched
Không đụng file production. Script đo mới: `scratch/calm_tf_probe.py`, `scratch/calm_mr_probe.py`;
kết quả: `scratch/calm_is.txt`, `scratch/on_long_calm.txt`, `scratch/on_long_calmnormal.txt`,
`scratch/on_long_calmnormal_c1.txt`.

### Bổ sung 2026-08-18 (cùng ngày) — chạy nốt hai phép còn treo

**1. Mean-reversion nội phiên trong Calm — KHÔNG có.** `scratch/calm_mr_probe.py`, khung nhãn
production. Kiểm công cụ PASS (chuỗi xáo trộn cho VR 0,976–1,013, đúng ~1).
Variance ratio 30 phút, trung bình 4 mã: **Calm 0,960 · Normal 0,985 · Stress 0,920**.
Cả ba nằm trong dải "bước ngẫu nhiên" (0,9–1,1). Trong Calm còn không đồng nhất giữa các mã
(MES 0,939 / M2K 0,940 nhưng MNQ 0,975 / MYM 0,986). Tương quan khoảng-hở↔phiên trong Calm
−0,156 (hở có fade nhẹ) nhưng cơ chế giao dịch được của nó — gap fill — đã đo và NO-GO.
Tương quan sáng↔chiều trong Calm −0,015 ≈ 0. Kiểm chéo: đếm được 708 ngày Calm trong IS,
trùng khít bảng regime đo độc lập.
Đáng ghi: **Stress mới là chỗ đảo chiều mạnh nhất** (0,920/0,898) — khớp với việc STRESS_MID
là lệnh fade, và ngược với trực giác "thị trường yên thì hay đảo chiều".

**2. Stop vũ trang 14h sau khi qua ngày mới — con số đẹp là ẢO GIÁC KHỚP LỆNH.**
`scratch/calm_tf_probe.py --stop-active-hour 14`. Mỏ neo PASS trên cả 4 mã, MES đối chiếu
thẳng engine PASS. Kết quả thô (1 hợp đồng, 2-tick, max_hold 5 ngày, IS 2018-2024):

| | quy ước BACKTEST (stop từ ranh giới ngày) | quy ước LIVE (vũ trang D+1 14:00) |
|---|---|---|
| PRODUCTION Normal+Stress | +$32.694 · PF 1,30 | +$108.041 · PF 2,33 |
| CALM | +$6.972 · PF 1,14 · 2/7 năm âm | +$46.826 · PF 2,25 · **7/7 năm dương, 4/4 mã dương** |

Nhìn qua thì Calm "sống dậy" dưới luật live. Nhưng đo tiếp thì lộ cơ chế:
**32,8% lệnh production và 35,0% lệnh Calm thoát ngay tại thời điểm stop lên sàn, và giá MỞ
của thanh bar đó đã nằm bên kia mức stop** — tức thị trường đã xuyên qua mức stop TRƯỚC khi
lệnh STP được đặt. Mô phỏng vẫn khớp tại MỨC STOP; live đặt STP vào thị trường đã xuyên qua
thì nó thành lệnh thị trường, khớp ở giá hiện hành (tệ hơn).
Tính lại phần chênh bằng đúng quy ước engine dùng cho GAP exit (khớp tại giá mở):
độ lệch trung vị $97/lệnh, tb $151, p95 $463, max $996.

| | mô phỏng | trừ phần khớp lệnh ảo | so với quy ước BACKTEST |
|---|---|---|---|
| PRODUCTION | +$108.041 | **+$7.388** (mất 93,2%) | thấp hơn $32.694 |
| CALM | +$46.826 | **−$10.665** (mất 122,8%) | âm |

Kết luận: khoảng ân hạn 14h **không tạo ra tiền** — nó dời chỗ thua từ "stop cắt sớm" sang
"khớp xa hơn khi cuối cùng cũng cắt", và phần dời đó lớn hơn phần được. Calm dưới luật live
là ÂM. Không có hướng Calm nào mở ra từ đây.

**Hệ quả vượt ra ngoài câu hỏi Calm — cần người quyết định nhìn:**
- Đợt "Khoảng ân hạn cho stop" (09/08, +$128.863 tại mốc 16h, qua 4 cửa, không áp dụng) dùng
  **cùng công cụ, cùng giả định khớp lệnh**. Bốn kênh rủi ro liệt kê ở đó KHÔNG có kênh này.
  Chưa đo lại mốc 16h nên **không sửa số của họ** — nhưng con số đó cần một dòng cảnh báo.
- Live ĐANG chạy luật 14h (OPERATIONS.md 10/08, có chủ đích), còn mọi baseline/sàn/vault đều
  tính theo quy ước backtest. Nếu phép hiệu chỉnh trên đúng, live được kỳ vọng **thấp hơn**
  baseline một cách có cấu trúc, chứ không phải bằng. Cần đối chiếu với sổ paper.
- CHƯA KIỂM KỸ: đường live làm gì khi mức stop đã bị xuyên qua lúc vũ trang — grep nhanh
  `repair_stops.py`/`ibkr_broker.py` không thấy nhánh xử lý riêng. Đây là 1/3 số lệnh, nên
  đọc kỹ đường đặt lệnh đó là việc tiếp theo đáng làm nhất.

### Files added (2026-08-18)
scratch/calm_tf_probe.py, scratch/calm_mr_probe.py, scratch/act_fill_gap.py,
scratch/calm_probe_*.csv (4 tệp lệnh), scratch/calm_is*.txt, scratch/calm_mr.txt,
scratch/act_fill_gap.txt, scratch/on_long_*.txt

### Bổ sung 2026-08-18 (lượt 3) — ĐO LẠI CHẶT điểm khớp lệnh, vì live đang chạy trên nó
`scratch/act_fill_verify.py`. Lấy luật vũ trang TỪ CODE LIVE (`runner._ARM_BY_CLUSTER` =
Rổ 4 America/New_York 14:00, NKD Asia/Tokyo 14:00) — đúng mốc 14h đã đo.

**Đối chứng quan trọng nhất:** với quy ước engine (stop từ ranh giới ngày), bộ phát hiện
"khớp tại mức đã bị xuyên qua" bắt được **0 lệnh**. Nó chỉ kêu khi có gì để kêu.
Mỏ neo: run_loop không hoãn tái tạo engine trùng khít cả 4 mã.

**Quét mốc vũ trang, Rổ 4 Normal+Stress, IS 2018-2024, 1 hợp đồng, 2-tick:**

| mốc vũ trang | số lệnh | P&L thô | tỷ lệ thoát GAP | số lệnh phải sửa | tổng sửa | **P&L hiệu chỉnh** | PF hc |
|---|---|---|---|---|---|---|---|
| engine (ranh giới ngày) | 2.496 | $32.694 | 5,3% | **0** | $0 | **$32.694** | **1,30** |
| 1,17h | 2.488 | $35.806 | 5,3% | 580 | $39.779 | −$3.974 | 0,97 |
| 5h | 2.423 | $49.092 | 5,1% | 609 | $54.729 | −$5.637 | 0,96 |
| 9,52h | 2.312 | $69.056 | 4,9% | 672 | $64.109 | $4.947 | 1,03 |
| 12h | 2.126 | $96.685 | 4,9% | 691 | $94.957 | $1.728 | 1,01 |
| **14h (live)** | 2.030 | **$108.041** | 5,3% | 665 | $100.653 | **$7.388** | 1,04 |
| 16h | 1.699 | $100.125 | 6,2% | 558 | $96.161 | $3.964 | 1,02 |
| 20h | 1.686 | $84.641 | 10,7% | 464 | $76.369 | $8.272 | 1,05 |

**Đường thô có đỉnh ở 14h. Đường hiệu chỉnh KHÔNG CÓ ĐỈNH NÀO** — nó phẳng quanh 0
(−$5.637 … +$8.272), PF 0,96–1,05 ở mọi mốc hoãn, trong khi không hoãn cho PF 1,30.
Tức là toàn bộ phần "lợi" của khoảng ân hạn nằm ở chỗ khớp lệnh không thể có thật, và sau
khi tính đúng thì **mọi mức hoãn đều kém hơn không hoãn**.

Độ lệch tại mốc 14h: 665/2.030 lệnh (33%), trung vị $97, tb $151, p95 $463, max $996.
Ví dụ soi mắt: MES 28/02/2018 LONG — mô phỏng khớp tại stop 3195,88 trong khi bar vũ trang
MỞ ở 3118,25 (lệch $388); cạnh đó có ca chỉ lệch $2,70. Phân bố hợp lý, không phải bắt bừa.

**Corroborate từ chính runner:** ghi chú `_ARM_BY_CLUSTER` nói vũ trang lúc 17–18h ET làm
tỷ lệ thoát GAP vọt 6%→40% và P&L sụp +$128.863→−$1.091. Quét của tôi tái hiện đúng chữ ký
đó: tại 20h tỷ lệ GAP tăng gấp đôi (5,3%→10,7%) và số lệnh cần tôi sửa GIẢM — vì engine bắt
đầu **tự nhìn thấy** cùng hiện tượng dưới dạng gap và tự khớp tại giá mở. Cùng một cơ chế;
engine chỉ tính tiền cho nó khi giờ nghỉ phiên làm nó lộ ra.

**Self-check SC4 FAIL — lỗi của phép kiểm, không phải của phép đo.** Tôi viết nó trên SỐ
TUYỆT ĐỐI lệnh bị sửa (580→609→672→691→665→558→464), trong khi tổng số lệnh cũng giảm theo
độ trễ. Trên TỶ LỆ thì đúng như dự đoán: 23%→25%→29%→32%→33%→33%, chỉ tụt ở 20h đúng chỗ
engine tự hấp thụ phần đó vào nhánh GAP.

**Calm tại mốc live, sau hiệu chỉnh: +$46.826 → −$10.665**, và "7/7 năm dương" thành 3/7:
2018 −2.061 · 2019 −1.639 · 2020 +111 · 2021 −10.625 · 2022 +1.586 · 2023 −2.902 · 2024 +4.865.

### Hệ quả — cần người quyết định
1. **Mốc 14h được CHỌN bằng walk-forward trên chính thước đo có sai lệch này** (runner ghi:
   h*=14h 6/7 năm Rổ 4, 7/7 MNKD, ngoài mẫu +$116.530). Walk-forward kiểm tính ổn định của
   lựa chọn, KHÔNG kiểm tính đúng của thước đo — sai lệch có mặt đồng đều ở mọi fold thì mọi
   fold đều đồng ý.
2. **Live đang chạy luật 14h; baseline/sàn/vault đều tính theo quy ước engine.** Nếu phép
   hiệu chỉnh đúng hướng, kỳ vọng của live là cột $7.388/PF 1,04 chứ không phải $32.694/PF 1,30
   — thấp hơn baseline một cách CÓ CẤU TRÚC, không phải xui.
3. **Paper chưa phân xử được:** mốc 2026-08-10, lãi lỗ đã đóng của paper mới −$43,25. n quá nhỏ.

### CHƯA KIỂM (đừng đọc thành đã đóng)
- Live có đặt lệnh bảo vệ nào khác trong 14h đó không (`disaster_mult` mặc định tắt trong mô
  phỏng — chưa tra đường live).
- IBKR **nhận hay từ chối** một STP đã bị xuyên qua. Nhận → khớp thị trường (đúng như hiệu
  chỉnh). Từ chối → vị thế **tiếp tục trần**, hình dạng khác hẳn và có thể tệ hơn. 1/3 số lệnh
  đi qua nhánh này. Đây là việc đáng làm nhất tiếp theo.
- Giả định khớp = GIÁ MỞ của bar vũ trang. Đó là đúng quy ước engine đang dùng cho GAP exit,
  nhưng vẫn là giả định; hướng thì không đổi (khớp tại mức đã bị bỏ lại là không thể).

### Bổ sung 2026-08-18 (lượt 4) — VÌ SAO ĐỢT KIỂM ĐỊNH 09/08 KHÔNG BẮT ĐƯỢC
`scratch/gate_rerun.py` — chạy lại ĐÚNG bốn cửa của đợt đó, cộng phép walk-forward đã chọn
14h, trên thước đo đã hiệu chỉnh khớp lệnh. Mỏ neo PASS, 5/5 self-check PASS.
Đối chứng then chốt: mốc "ranh giới ngày" bị hiệu chỉnh **0 lệnh**.

| mốc | lệnh bị sửa | P&L thô | P&L hiệu chỉnh | năm thắng thô | năm thắng hc | IS thô | IS hc | VAULT thô | VAULT hc |
|---|---|---|---|---|---|---|---|---|---|
| ranh giới ngày | 0 | 32.694 | **32.694** | — | — | 24.655 | 24.655 | 8.038 | 8.038 |
| 1,17h | 580 | 35.806 | −3.974 | 5/7 | **0/7** | 27.743 | −4.428 | 8.063 | 454 |
| 5h | 609 | 49.092 | −5.637 | 7/7 | **0/7** | 39.965 | −4.012 | 9.127 | −1.625 |
| 9,52h | 672 | 69.056 | 4.947 | 7/7 | **0/7** | 52.492 | 3.249 | 16.563 | 1.698 |
| 12h | 691 | 96.685 | 1.728 | 7/7 | **0/7** | 71.712 | 28 | 24.973 | 1.700 |
| **14h (live)** | 665 | 108.041 | 7.388 | 7/7 | **1/7** | 76.776 | **−1.370** | 31.265 | 8.758 |
| 16h | 558 | 100.125 | 3.964 | 7/7 | 3/7 | 68.161 | −6.398 | 31.964 | 10.362 |
| 20h | 464 | 84.641 | 8.272 | 7/7 | 3/7 | 56.673 | −2.172 | 27.968 | 10.444 |

**Từng cửa mù ở đâu:**
- **Cửa 1 (vùng cao rộng chứ không nhọn)** phân biệt NHIỄU với CẤU TRÚC. Một sai lệch hệ
  thống tăng đều theo tham số *cũng là* cấu trúc — trơn và rộng. Đường hiệu chỉnh phẳng
  (−5.637…+8.272): cao nguyên đó là hình dạng của sai lệch.
- **Cửa 2 (tách năm, 9/9)** phân biệt MỘT SỰ KIỆN với QUY LUẬT LẶP LẠI. Sai lệch có mặt ở
  mọi năm thì lặp lại theo cấu tạo. Hiệu chỉnh: 7/7 → **1/7** tại 14h.
- **Cửa 3 (IS/VAULT ngoài mẫu)** phân biệt KHỚP QUÁ DỮ LIỆU với HIỆU ỨNG THẬT TRONG DỮ LIỆU.
  Nhưng sai lệch không nằm trong dữ liệu — nó nằm trong **mã định giá lệnh thoát**. Dữ liệu
  ngoài mẫu vẫn chảy qua đúng đoạn mã đó nên mang sai lệch theo. Ngoài mẫu kiểm giả thuyết,
  không kiểm được thước đo. Hiệu chỉnh: IS tại 14h **−1.370** (baseline 24.655).
- **Cửa 4 (đối chứng nới độ rộng — cửa họ gọi là quan trọng nhất) BỊ NHIỄM.** Đo được:

  | ×độ rộng | số lệnh | **lệnh bị sửa** | P&L thô | P&L hiệu chỉnh |
  |---|---|---|---|---|
  | 1,0× | 2.488 | **580** | 35.806 | −3.974 |
  | 2,0× | 2.194 | **300** | 16.554 | −3.043 |
  | 6,0× | 1.530 | **54** | −27.933 | −31.761 |

  Nới stop **tắt dần chính cái sai lệch** (580→300→54): stop càng xa thì càng ít khi tới lúc
  vũ trang giá đã ở bên kia. Nên đường thô dốc xuống một phần vì sai lệch bị gỡ đi, không
  phải chỉ vì stop rộng thì tệ. Sau hiệu chỉnh, 1,0× (−3.974) và 2,0× (−3.043) **gần như
  bằng nhau** — tính đơn điệu biến mất. Hai nhánh chưa bao giờ được đo trên cùng một thước.
  Thêm nữa: trong bản đã commit, vòng lặp bảng độ rộng chạy trên danh sách **rỗng**
  (`for w in []`, chú "đã chạy ở lần trước") — số trong báo cáo là dán từ lượt trước.

**Phép quyết định — chạy lại chính walk-forward đã chọn 14h:**

| | h* chọn từ quá khứ, từng năm | tổng ngoài mẫu |
|---|---|---|
| thô (như đợt 09/08) | 16h, 14h, 14h, 14h, 14h | $88.071 |
| **hiệu chỉnh** | **ranh giới ngày ×5** | $25.495 |

Trên số đã hiệu chỉnh, thủ tục chọn của chính họ **không bao giờ chọn hoãn** — 5/5 năm chọn
không hoãn. Walk-forward kiểm tính ổn định của lựa chọn; nó không thể phát hiện sai lệch có
mặt đồng đều ở mọi fold, vì mọi fold đều đồng ý với nhau.

**Bằng chứng đã ở ngay trước mặt và bị đọc sai loại.** Ghi chú `_ARM_BY_CLUSTER` chép rằng
vũ trang lúc 17–18h ET làm tỷ lệ thoát GAP vọt 6%→40% và P&L sụp +$128.863→−$1.091. Đó
chính là hiện tượng này, chỉ khác là giờ nghỉ phiên gắn cờ gap nên engine NHÌN THẤY và tự
khớp tại giá mở. Nó được kết luận thành ràng buộc "đừng vũ trang ở ranh giới phiên" — một
câu về LỊCH — thay vì câu hỏi "vì sao đúng sự kiện đó ở giữa phiên lại không tốn đồng nào".

### Vẫn chưa kiểm
- IBKR **nhận hay từ chối** STP đã bị xuyên qua (nhận → khớp thị trường đúng như hiệu chỉnh;
  từ chối → vị thế tiếp tục trần, hình dạng khác). 1/3 số lệnh đi qua nhánh này.
- **Ratchet rời rạc**: mô phỏng kéo stop theo từng bar; live chỉ dời stop khi có job chạy.
  Cùng họ sai lệch, chiều ngược lại, chưa ai đo.
- Hiệu chỉnh giả định khớp tại GIÁ MỞ của bar vũ trang — đúng quy ước engine dùng cho GAP
  exit, nhưng vẫn là giả định. Hướng thì không đổi.

### Bổ sung 2026-08-18 (lượt 5) — TỰ ĐÍNH CHÍNH: đối chứng của tôi cũng hỏng
`scratch/control_fix.py`. Lượt 4 tôi báo "quy ước engine bị hiệu chỉnh 0 lệnh" và gọi đó là
đối chứng. **Sai**: hàm hiệu chỉnh có dòng `if H is None: return 0.0`, nên đối chứng PASS
theo cấu tạo chứ không theo đo lường — đúng loại "test xanh mà không kiểm gì".

Quy ước engine cũng có quãng trần: vào lệnh 14:00–15:55 ngày D nhưng chỉ bị xét stop từ D+1,
tức ~8–10 tiếng không có lệnh dừng. Đo histogram: **24,0% số lệnh thoát ngay trong PHÚT ĐẦU
của D+1**, và **cả 600 lệnh đó đều mang nhãn CHANDELIER (khớp tại mức stop), 0 lệnh nhãn GAP**.

Chạy lại toàn dải với H=0.0 (đã chứng minh trùng khít engine trên cả 4 mã) — mọi cột cùng
một bộ phát hiện:

| mốc | n | n sửa | %sửa | P&L thô | **P&L hiệu chỉnh** | trung vị lệch | tổng sửa |
|---|---|---|---|---|---|---|---|
| **0h (= engine, baseline)** | 2.496 | 591 | 23,7% | 32.694 | **−6.210** | $40 | $38.904 |
| 1,17h | 2.488 | 580 | 23,3% | 35.806 | −3.974 | $40 | $39.779 |
| 5h | 2.423 | 609 | 25,1% | 49.092 | −5.637 | $53 | $54.729 |
| 9,52h | 2.312 | 672 | 29,1% | 69.056 | 4.947 | $67 | $64.109 |
| 14h (live) | 2.030 | 665 | 32,8% | 108.041 | 7.388 | $97 | $100.653 |
| 16h | 1.699 | 558 | 32,8% | 100.125 | 3.964 | $118 | $96.161 |
| 20h | 1.686 | 464 | 27,5% | 84.641 | 8.272 | $111 | $76.369 |

**RÚT LẠI câu ở lượt 4:** tôi đã viết "mọi mức hoãn đều kém hơn không hoãn ($32.694/PF 1,30)".
Câu đó so một cột ĐÃ hiệu chỉnh với một cột CHƯA hiệu chỉnh — đúng lỗi so khác cơ sở.
Trên cùng cơ sở, **toàn bộ bề mặt phẳng và quanh 0**: −6.210 … +8.272 trên 7 năm, 1 hợp đồng.
Không có mốc vũ trang nào cho ra lợi thế.

Walk-forward trên số đã hiệu chỉnh đúng cơ sở: h* = 20h, 20h, 20h, 9,52h, 14h — **không ổn
định**, tổng ngoài mẫu **−$6.226**. Đúng hình dạng của "không có hiệu ứng thật để chọn".

### VÌ SAO KHÔNG PHÉP KIỂM CŨ NÀO BẮT ĐƯỢC — cơ chế, không phải suy đoán
1. **Luật đúng ĐÃ CÓ trong code, nhưng bị khoá sau điều kiện sai.** Nhánh thoát:
   `gapped = gap_fill and isg[i] and (giá mở đã vượt mức stop)` → khớp tại giá mở, nhãn GAP;
   ngược lại → khớp tại mức stop, nhãn CHANDELIER. Cờ `isg` trả lời "trước bar này có nghỉ
   phiên không", KHÔNG trả lời "lệnh stop vừa mới được đặt". Giữa phiên `isg` = False nên
   nhánh giá-mở không bao giờ chạy. Bằng chứng: trong số lệnh thoát ở phút đầu tiên stop tồn
   tại, **0 lệnh nhãn GAP**, 600 (engine) / 697 (14h) nhãn CHANDELIER.
2. **Nên không con số nào trong báo cáo cũ có thể lộ ra.** Mọi cửa kiểm đọc P&L và MaxDD, mà
   cả hai đều tính TỪ giá thoát. Giá thoát sai thì mọi thống kê phía sau sai cùng chiều, đều
   đặn, ở mọi năm và mọi giai đoạn. Bảng tự nhất quán với chính nó — và sai với bên ngoài.
3. **Cột đến gần nhất lại đo nhầm đại lượng, và nhãn của nó hứa đúng đại lượng.** Bảng sweep
   in "lỗ tạm khi trần" (MAE tính từ GIÁ VÀO) kèm cột ">2×". Chú thích viết là đếm số lần lỗ
   tạm vượt **hai lần khoảng cách stop** — đúng thứ cần. Code lại tính `x > 2*median(mae)` —
   hai lần TRUNG VỊ CỦA CHÍNH MẪU, một thước phân tán, so mẫu với chính nó. Nên chưa từng có
   con số nào trong bảng đó so giá với MỨC STOP. Nó ra 28–31%, nằm ngay cạnh cột P&L, và được
   xếp vào ô "rủi ro".
4. **Chữ ký hiển nhiên chưa ai vẽ:** tỷ lệ lệnh thoát trong phút ĐẦU TIÊN stop tồn tại —
   engine 24,0%, mốc 14h 34,3%. Một phần tư tới một phần ba số lệnh dồn vào đúng một phút chỉ
   có thể xảy ra nếu những lệnh đó đang định giá một sự việc đã xảy ra từ trước.

### Hệ quả mới, lớn hơn câu hỏi Calm và câu hỏi 14h
Câu hỏi không còn là "hoãn 14h có tốt không" mà là **bao nhiêu phần của lợi thế swing TF đo
được đến từ giả định khớp lệnh tại mức stop ở lần xét stop đầu tiên sau quãng trần**.
Trên khung 1 hợp đồng/IS, phép hiệu chỉnh đưa +$32.694 về −$6.210.
CHƯA làm: dựng lại baseline triển khai ($42.459, có sizing + cap) dưới luật khớp lệnh này —
nên KHÔNG được nói "baseline sai $39k"; mới chỉ nói được trên khung 1 hợp đồng.

### Bổ sung 2026-08-18 (lượt 6) — BASELINE TRIỂN KHAI DƯỚI LUẬT KHỚP LỆNH ĐÃ SỬA
`scratch/baseline_corrected.py`. Đưa phép sửa vào ĐÚNG đường sinh ra baseline (`deploy_sim`,
có sizing + net-exposure cap + circuit breaker), bằng cách thay thuộc tính `backtest_swing_tf`
trên module lúc chạy — **không sửa một dòng mã production nào**.

| lượt | net | Calmar | PF | Sharpe | MaxDD | breaker halt | swing vào lệnh |
|---|---|---|---|---|---|---|---|
| **1 GỐC (nguyên bản)** | **$42.459** | **1,72** | 1,48 | 1,67 | $3.574 (7,1%) | **0** | 1.799 |
| 2 GỐC + sửa khớp lệnh | **−$2.240** | −0,05 | 0,98 | −0,12 | $8.655 (**17,3%**) | **925** | 1.274 |
| 3 LIVE 14h (thô) | $105.451 | 10,51 | 2,61 | 3,84 | $1.451 (2,9%) | 0 | 1.459 |
| 4 **LIVE 14h + sửa** | **$2.652** | 0,07 | 1,03 | 0,14 | $9.387 (**18,8%**) | **1.042** | 904 |

Lượt 1 tái tạo **chính xác** mốc ghim trong INVARIANTS ($42.459 / Calmar 1,72 / MaxDD $3.574),
nên đường chạy là đúng đường. Phép sửa ở lượt 4: 893 lệnh, $125.131 trên cơ sở 1 hợp đồng
trước khi nhân sizing.

**Mâu thuẫn cốt lõi, nói gọn:** baseline lấy luật "chưa có stop tới ngày hôm sau" để quyết
định **KHI NÀO** được thoát, nhưng lấy luật "stop đã nằm sẵn trên sàn" để quyết định **GIÁ
NÀO**. Hai luật đó không thể cùng đúng. Bắt nó nhất quán theo hướng nào cũng sụp:
- nhất quán "chưa có stop" (khớp tại giá thị trường lúc lệnh xuất hiện): $42.459 → **−$2.240**
  (vũ trang nửa đêm) hoặc **+$2.652** (vũ trang 14:00, đúng luật live đang chạy)
- nhất quán "stop có từ lúc khớp": số của chính dự án ghi trong `runner._stop_deferred` là
  **−$10.832** (khác cơ sở phí/kỳ, TÔI CHƯA đo lại — trích chứ không dựa vào)

Con số $42.459 nằm trong khe giữa hai luật.

**Rủi ro đi kèm, không chỉ P&L:** MaxDD 7,1% → **17,3%/18,8%**, vượt trần cứng 15%; và
circuit breaker chuyển từ **0 lần** (INVARIANTS ghi "HALT chưa bao giờ được kích hoạt trong
7 năm, UNTESTED") sang **925–1.042 lần**. Chính việc breaker chặn là thứ kéo net về gần 0 —
tức phanh làm việc, nhưng nó phải làm việc liên tục.

### Đường live khi stop đặt vào thị trường đã xuyên qua — ĐỌC TỪ CODE
`ibkr_broker.place_stop` **không kiểm giá thị trường** trước khi đặt; nó gửi `StopOrder`
(GTC, outsideRth) rồi chờ `_await_stop_accepted`. Hàm đó chỉ coi `PreSubmitted`/`Submitted`
là được nhận, còn **`Filled` nằm trong nhóm "chết"**. Nên nếu lệnh khớp ngay trong 5 giây
chờ (đúng thứ xảy ra khi giá đã ở bên kia mức stop), hàm trả về "KHÔNG được nhận",
`place_stop` trả chuỗi rỗng, và runner ghi sổ là **vị thế đang trần** trong khi vị thế vừa
bị ĐÓNG. Lớp B3 có đối soát vị thế với broker nên nhiều khả năng bắt lại ở slot sau —
**chưa xác minh**, và chưa quan sát thấy ca thật. Dù nhánh nào thì cũng không phải "khớp tại
mức stop" như mô phỏng giả định.

### Chưa làm
- Chưa dựng lại vault 2023-24 / 2025 và sàn Calmar dưới luật đã sửa.
- Chưa tự đo lại nhánh "stop có từ lúc khớp" (mới trích số của dự án).
- **Sai lệch ngược chiều chưa đo**: mô phỏng kéo stop theo từng bar, live chỉ dời stop khi có
  job chạy — trên lệnh thắng live giữ mức cũ lâu hơn, có thể bù lại một phần.
- Giả định khớp = giá MỞ của bar vũ trang (đúng quy ước engine dùng cho GAP exit), chưa đối
  chiếu với fill thật.

### Bổ sung 2026-08-18 (lượt 7) — THỬ PHÁ KẾT QUẢ CỦA CHÍNH MÌNH
Phản biện: "baseline chạy đi chạy lại nhiều lần, không lẽ không ai thấy". Đi kiểm ba hướng.

**(a) Đọc thẳng bar 1 phút từ parquet, không qua bộ phát hiện của tôi** (`scratch/eyeball_path.py`):
- MNQ LONG vào 05/09/2024, mức stop 19486,41 → hôm sau giá dưới mức stop **ngay từ bar 00:00**
  (mở 19381), rơi cả ngày, lúc 14:00 ở **18988,5 = thấp hơn 498 điểm**. Ở bên kia mức stop
  **840 phút** trước giờ vũ trang. Mô phỏng ghi thoát tại 19486,41.
- MNQ SHORT vào 12/05/2022, stop 13809,1 → 14:00 ở **14293,75, cao hơn 485 điểm**.
- M2K LONG stop 1923,42 → 14:00 ở 1904,6.
Cơ chế là thật, không phụ thuộc giả định khớp lệnh.

**(b) Các đợt đối soát đã chạy so cái gì với cái gì** — đọc docstring từng tệp:
`reconcile_gd0`: SwingTFEngine.backtest == backtest_swing_tf — chính docstring viết
*"true by construction"*. `reconcile_nkd`: cùng thế, *"proves the class interface is wired
correctly"*. `reconcile_swing_desired`: desired_position == backtest_basket.
`reconcile_stress`: entry_signal == adapter. **Bốn trên năm là so hệ với chính nó** — hai vế
đều gọi `backtest_swing_tf`, nên đều mang cùng luật khớp lệnh, và khớp nhau tới từng xu đúng
như một giả định dùng chung phải cho ra. Đợt duy nhất có nguồn độc lập là `reconcile_statement`
(sao kê IBKR) — chính nó viết *"the one account the runner did not author"*.

**(c) Giả định ĐÃ được đăng ký, nhưng phép kiểm gắn với nó đo sai chiều.** `ASSUMPTIONS.md`
có dòng `Fill rate ~100% (fill-at-price) | Backtest assumption | Paper — đo skip rate thực tế`.
Câu hỏi được giao là "có được khớp không"; lỗi nằm ở "khớp ở GIÁ NÀO". Lệnh vẫn khớp 100%
nên phép kiểm đó không có khả năng đỏ.

**BẰNG CHỨNG THẬT — và nó KHÔNG ủng hộ tôi, phải ghi ra:**
- Sổ paper có đúng **2** lần stop nổ thật: 06/08 M2K stop 3038,5 khớp 3038,6 (1 tick);
  07/08 M2K stop 3020,1 khớp **3020,1** (đúng mức). Cả hai là "thị trường đi tới chạm stop
  nằm sẵn", KHÔNG phải "đặt stop vào thị trường đã đi qua".
- Nhật ký paper có **10 lần đặt stop, tất cả PreSubmitted, 0 lần NOT ACCEPTED** → chưa từng
  quan sát được tình huống đang bàn. Nhưng nhiều lần trong số đó là đặt lại cùng một stop
  (MES @7769,25 lúc 13:10/13:20/13:30), nên số sự kiện vũ trang riêng biệt chỉ ~4. Với p=1/3,
  xác suất 0/4 là ~20% — **n quá nhỏ để nói gì, theo cả hai chiều**.

**Trạng thái đúng:** cơ chế đã xác minh trên dữ liệu lịch sử; độ lớn bằng tiền là MÔ HÌNH
(khớp tại giá mở); live có **0 quan sát**. Cần paper chạy tới khi có vài lần stop được vũ
trang vào thị trường đã xuyên qua thì mới phân xử được bằng thực tế.

### Bổ sung 2026-08-18 (lượt 8) — RATCHET đóng lại; và TỰ ĐÍNH CHÍNH lần hai
`scratch/ratchet_x_fill.py`, `scratch/baseline_noratchet.py`, `scratch/baseline_half.py`.

**1. "Ratchet rời rạc" mô tả sai. Live KHÔNG ratchet gì cả.** `runner.py` ghi thẳng:
*"stop_price = entry chandelier level; ratchet updates are not yet implemented (planned for
a future phase — paper phase uses fixed entry-stop)"*. Stop giữ nguyên mức lúc vào lệnh suốt
đời lệnh.

**2. Trục ratchet KHÔNG bù được gì** (lưới 1 hợp đồng, IS, 2-tick):

| vũ trang | ratchet | lệnh | P&L thô | n sửa | tổng sửa | P&L đã sửa |
|---|---|---|---|---|---|---|
| ranh giới ngày | có | 2.496 | 32.694 | 591 | 38.904 | −6.210 |
| ranh giới ngày | không (live) | 2.494 | 32.789 | 591 | 38.904 | −6.115 |
| 14h | có | 2.030 | 108.041 | 665 | 100.653 | 7.388 |
| **14h** | **không (live)** | 2.027 | 108.086 | 664 | 100.562 | **7.524** |

Bỏ ratchet chỉ làm phần sửa giảm **$91 trên $100.653** (0,09%). Lý do: ratchet gần như không
cắn — chỉ 2–7 lệnh trên ~2.500 đổi lý do thoát, khớp với ghi chép cũ *"stop chỉ ratchet lên
trên entry 1,6% số lần"*; dải chandelier 2,5×ATR ngày quá rộng so với kỳ nắm 5 ngày.
Tái tạo được kết luận cũ (+$132) trên cơ sở của tôi: +$95 / +$45. **Trục này đóng.**

**3. TỰ ĐÍNH CHÍNH — tôi đã nói quá tay.** Lượt trước tôi viết *"khoảng đúng không chứa
+$42.459"*. **Sai.** Ở tầng deploy, chạy lại với đầu rộng lượng của dải khớp lệnh:

| cấu hình (deploy, 1 micro, IS, 2-tick) | net | Calmar | MaxDD | breaker halt |
|---|---|---|---|---|
| baseline công bố | $42.459 | 1,72 | 7,1% | 0 |
| luật live (14h, stop cố định), khớp tại **mức stop** | $105.496 | 10,52 | 2,9% | 0 |
| luật live, khớp **GIỮA** stop và giá mở | **$58.151** | **1,69** | 10,0% | **0** |
| luật live, khớp tại **giá mở** | **$2.814** | **0,07** | 18,8% | **1.042** |

Dải ở tầng deploy **rộng hơn nhiều** so với tầng 1 hợp đồng, vì circuit breaker là ngưỡng:
ở giả định giữa, DD dừng ở 10,0% nên phanh **không nổ lần nào** và hệ giao dịch đủ cỡ; ở giả
định giá mở, DD lên 18,8%, phanh nổ 1.042 lần và cắt hết. Giả định khớp lệnh quyết định hệ
rơi về bên nào của cái ngưỡng đó.

**Trạng thái đúng:** giả định "khớp tại mức stop" là **không thể** với ~1/3 số lệnh (đã xác
minh trên bar thật). Nhưng độ lớn bằng tiền chưa đo được, và dải hợp lý trải từ **Calmar 1,69
(trên sàn 1,65)** tới **Calmar 0,07**. Baseline $42.459 NẰM TRONG dải đó. Không được nói
baseline sai; phải nói **giá trị của nó phụ thuộc một đại lượng chưa ai đo**.

**Đây giờ là đại lượng chưa đo lớn nhất của hệ.** Đo được bằng một thay đổi nhỏ: mỗi lần đặt
STP ghi kèm giá thị trường lúc đó, và mỗi lần stop khớp ghi kèm mức stop đã đặt. Hiện sổ paper
có 2 lần stop khớp, cả hai đều là "thị trường đi tới chạm stop nằm sẵn" — 0 quan sát cho
tình huống đang bàn.

### Bổ sung 2026-08-18 (lượt 9) — RÚT LẠI cột "khớp giữa"; số cuối cùng
Phản biện đúng: *"giá đã đi qua rồi thì giá chỉ là giá thị trường thôi"*. Cột **"khớp giữa
mức stop và giá thị trường" KHÔNG PHẢI kịch bản vật lý** — lệnh dừng đã bị vượt thì thành
lệnh thị trường, mà lệnh thị trường không khớp tốt hơn giá thị trường. Tôi đã bịa ra phép nội
suy đó để bắc cầu và trình bày nó như một đầu của dải; làm thế là thổi phồng mức không chắc
chắn. **Rút lại cột đó và rút lại luôn câu "dải có chứa $42.459" ở lượt 8.**

Tinh chỉnh thật sự cần: luật vũ trang là 14:00 nhưng lệnh chỉ được đặt khi CÓ JOB CHẠY —
job đầu tiên sau đó là **14:05**. Quét các mốc đặt lệnh khả dĩ (`scratch/fill_at_placement.py`,
ratchet=False = luật live, 1 hợp đồng, IS):

| mốc đặt lệnh | lệnh | P&L thô | n sửa | tổng sửa | P&L đã sửa | trung vị lệch |
|---|---|---|---|---|---|---|
| 14:00 (luật vũ trang) | 2.027 | 108.086 | 664 | 100.562 | 7.524 | $98 |
| **14:05 (job thật)** | 2.018 | 109.000 | 645 | 99.502 | **9.497** | $99 |
| 14:10 | 2.009 | 108.815 | 667 | 104.174 | 4.642 | $102 |
| 14:30 | 1.965 | 105.334 | 636 | 100.811 | 4.523 | $106 |

Dịch mốc trong nửa tiếng chỉ làm kết quả nhúc nhích $4,5k–9,5k trên nền hiệu chỉnh ~$100k.
**Không còn dải nào từ trục giá khớp.**

**Tầng deploy, mốc job thật 14:05, stop cố định, khớp tại giá thị trường** (`baseline_1405.py`):
**net $3.716 · Calmar 0,09 · PF 1,04 · MaxDD $9.603 (19,2%) · breaker halt 1.072 · swing vào
lệnh 891**. (Bản 14:00 cho $2.814 / 0,07 / 18,8% / 1.042 — cùng chỗ.)

### BẢNG CUỐI — chỉ giả định vật lý
| cấu hình (deploy, 1 micro, IS 2018-2024, 2-tick) | net | Calmar | MaxDD | halt |
|---|---|---|---|---|
| baseline công bố | $42.459 | 1,72 | 7,1% | 0 |
| luật live, khớp tại mức đã đặt — **không thể xảy ra** | $105.496 | 10,52 | 2,9% | 0 |
| **luật live, khớp tại giá thị trường lúc đặt** | **$3.716** | **0,09** | **19,2%** | **1.072** |

### Tôi đã đổi ý ba lần về cùng câu hỏi này — ghi lại để khỏi lặp
(1) baseline → −$2.240, dải không chứa $42.459 → (2) rút: dải CÓ chứa, vì "khớp giữa" cho
$58.151 → (3) rút tiếp: "khớp giữa" không có thật, số cuối là ~$3.700 và $42.459 KHÔNG nằm
trong đó. Con số chấm dứt tranh luận là **tính ổn định qua các mốc đặt lệnh** ở bảng trên,
không phải lập luận.

### Ẩn số còn lại KHÔNG phải giá, mà là NHÁNH
Nếu IBKR **từ chối** lệnh STP đã bị vượt (thay vì kích hoạt và khớp thị trường), thì không có
cú thoát nào tại thời điểm đặt: vị thế tiếp tục trần và kết cục khác hẳn — có thể tốt hơn
hoặc tệ hơn. Đó là câu hỏi nhị phân về hành vi broker, không phải dải giá, và chỉ trả lời
được bằng quan sát thật. Hiện có 0 quan sát.

### Bổ sung 2026-08-18 (lượt 10) — WFO độ rộng + stop theo ATR ngày; và BA TRỤC KHÔNG TÁCH RỜI
`scratch/wfo_stop_width.py`, `scratch/daily_atr_stop.py`, `scratch/interaction_grid.py`.
Tất cả trên thước đo ĐÃ SỬA khớp lệnh, vũ trang D+1 14:05, ratchet=False.

**Cấu trúc — xác nhận độc lập:** khoảng cách stop ban đầu / (mult × ATR **ngày**) = trung vị
**1/21 · 1/23 · 1/21 · 1/21** trên MES/MNQ/MYM/M2K. Đúng con số ~1/22 runner ghi. Nguyên nhân:
stop lấy từ **ATR 5 phút**, dải trail và mẫu số sizing lấy từ **ATR ngày**. Lệnh giữ 5 ngày
dùng mức dừng đo bằng nhịp 5 phút.

**Quét độ rộng cô lập** (`stop_width_mult`): đơn điệu xấu trên thước đã sửa — 1,0× $9.497 ·
2,0× $1.574 · 5× −$11.287 · 20× −$29.889. Nới stop CÓ gỡ lỗi khớp lệnh (645→23 lệnh dính)
nhưng phá P&L nhanh hơn. WF: chọn 1,0× ở 4/5 năm, **OOS −$12.812**.

**Stop tính thẳng từ ATR ngày** (f × ATR ngày, giữ nguyên tập lệnh vì `atr` chỉ vào
`initial_stop`, dòng 416 trend_follow.py): cơ chế sạch — lệnh dính lỗi khớp 655→129, tổng sửa
$100.887→$19.057, lệnh bị quét 1400→338, sống tới trần 511→897. Nhưng P&L không tốt lên:
tốt nhất f=0,25 ($8.308) ≈ hiện trạng. WF: **OOS −$6.024**.

**RÚT LẠI "ba trục đã đóng".** Lưới tương tác cho thấy argmax DỊCH khi đổi cơ sở stop:

| max_hold (ema=30) | f=0,12 | f=0,5 | f=2,5 |
|---|---|---|---|
| 3 | **11.469** | 379 | −4.932 |
| 5 | 6.807 | 199 | −8.785 |
| 7 | 8.770 | 9.873 | **30.527** |
| 10 | 10.188 | **14.299** | 18.433 |

| ema (hold=5) | f=0,12 | f=2,5 |
|---|---|---|
| 20 | 5.844 | −5.875 |
| 30 | 6.807 | −8.785 |
| 50 | **10.246** | −12.824 |

hold tốt nhất đi 3 → 10 → 7; ema tốt nhất lật 50 → 20. Mọi phép quét một trục trước đó đều
giữ hai trục kia ở giá trị **WFO gốc chọn dưới thước đo hỏng** — nên chúng là lát cắt qua một
mặt tại một điểm không phải tối ưu của mặt đó. Kết luận "không trục nào cứu được" chỉ đúng cho
lát cắt, không đúng cho cả mặt.

**KHÔNG coi ô $30.527 là phát hiện.** Ở f=2,5, hold 5→7 nhảy −8.785 → +30.527 rồi 7→10 tụt về
18.433 — đỉnh nhọn giữa hai thung lũng, chênh $39k cho một bước tham số, và tìm ra bằng cách
quét trong mẫu rồi nhìn đáp án. Trạng thái đúng: **CHƯA BIẾT**, không phải "hết edge" cũng
không phải "có cấu hình $30k".

Đang chạy: `scratch/joint_wfo.py` — lưới chung 3×4×5 = 60 ô, tách theo năm, kèm walk-forward
chọn ô trên năm trước đo ở năm sau, và kiểm cao nguyên quanh ô tốt nhất.

### Bổ sung 2026-08-18 (lượt cuối) — HARNESS gom lại, có cổng mỏ neo
`scratch/harness.py`. Gom hơn hai mươi script rời của phiên thành một tệp. **Không sao chép
dòng code engine nào** — gọi thẳng hàm production, tiêm bản sửa ở ranh giới.

**Bốn cờ, mặc định TẮT:** `--fix-fill` (giá khớp đúng khi stop lên sàn vào thị trường đã đi
qua) · `--fix-entry` (bắt nến resume đúng chiều) · `--stop-basis f` (stop = f×ATR ngày) ·
`--arm H` / `--no-ratchet` / `--disaster m` / `--all-sleeves`.

**Cổng mỏ neo — chạy trước mọi thứ, không PASS thì thoát:** mọi cờ tắt phải tái tạo đúng
$42.459/1,72 · $42.565/1,65 · $10.757/2,86 · $7.404/2,54. **Đã PASS cả bốn.**
Tầng neo thứ hai: bật cờ live thì ra đúng $3.716/0,09 của lượt đo riêng lẻ.

**Nó bắt lỗi ngay lần chạy đầu**: hai lượt chạy của tôi trong phiên khác nhau ở chỗ có áp
bản sửa cho NKD hay không ($26.767 so với $3.716). Live thì NKD cũng hoãn stop và cũng không
ratchet, nên `--all-sleeves` mới là mô hình đúng.

**Cam kết trước, viết trong docstring của tệp** để sau này không nới: WFO có fold trên thước
đã sửa (không chọn từ lưới) · kỳ giữ riêng 2025 chưa từng dùng để chọn · đòi cao nguyên
(ô kề bên trong ±30%) · không năm nào đóng góp quá nửa · sàn Calmar dựng lại trên cùng cơ sở
trước khi so.

Production, config, paper: **không đụng**. Paper tiếp tục cấu hình hiện tại để thu dữ liệu
khớp lệnh — đó là nhiệm vụ của nó bây giờ.

### Bổ sung 2026-08-19 — SỬA ĐIỂM VÀO: đo ở tầng deploy, KHÔNG áp dụng
Chạy qua harness: `--arm 14.0833 --no-ratchet --fix-fill --all-sleeves --fix-entry`.

| cấu hình (deploy, baseline IS, 1 micro, 2-tick) | net | Calmar | MaxDD | phanh nổ |
|---|---|---|---|---|
| luật live + sửa khớp lệnh | $3.716 | 0,09 | 19,2% | 1.072 |
| **+ lọc hướng nến resume** | **−$3.540** | **−0,10** | 16,7% | 864 |

**Ngược dấu với phép đo 1 hợp đồng (+$1.180).** Xác nhận cảnh báo đã nêu trước khi chạy:
breaker là ngưỡng phi tuyến nên kết quả 1 hợp đồng KHÔNG mang sang deploy được. Từ nay mọi
kết luận về can thiệp phải đo ở tầng deploy, không được suy từ 1 hợp đồng.

**KHÔNG áp dụng**, ba lý do: (1) đổi dấu giữa hai nửa ở tầng 1 hợp đồng; (2) −$7.256 ở deploy;
(3) loại 46% tín hiệu để đổi lấy điều đó.

Khuyết tật vẫn THẬT (code không làm đúng docstring; nó sinh ra hình học stop 1/21 và 42 ca
stop sai phía) — nhưng cách sửa đơn giản nhất không cải thiện gì.

Khuôn chung của toàn bộ can thiệp đã thử trong hai phiên: **rủi ro dịch được, lợi nhuận thì
không.** Ở đây MaxDD 19,2%→16,7% và phanh nổ 1.072→864, còn P&L đi xuống.

### Bổ sung 2026-08-19 (lượt 2) — SỬA ĐÚNG CÁCH ở điểm vào: LỌC BỎ ≠ SỬA
Phản biện: *"sao không sửa phần lệnh vào cho đúng hẳn mà chỉ lọc bỏ?"* — đúng. Lọc bỏ vứt
46% cơ hội đi; sửa thật là **quét tới cây nến mà docstring đã mô tả** rồi vào lệnh ở đó.
Thêm hai bản sửa vào harness, kèm **tự kiểm bộ quét** (chế độ không lọc phải trùng khít
`build_sig_cache`: 818/838/865/835 tín hiệu, MATCH cả 4 mã — cổng mỏ neo không phủ được
chỗ này vì cổng chạy với mọi cờ tắt).

Deploy, baseline IS, 1 micro, 2-tick. Cổng mỏ neo PASS 4/4 đầu lượt.

| cấu hình | net | Calmar | MaxDD | phanh nổ | lệnh dính lỗi khớp | tiền sửa |
|---|---|---|---|---|---|---|
| mốc so: luật live + sửa khớp lệnh | $3.716 | 0,09 | 19,2% | 1.072 | 876 | $123.527 |
| LỌC BỎ nến sai chiều | −$3.540 | −0,10 | 16,7% | 864 | 689 | $93.957 |
| **A. QUÉT TỚI nến đúng chiều** | **$12.832** | **0,24** | **15,6%** | **0** | 762 | $101.974 |
| B. stop neo vào giá vào | $2.991 | 0,07 | 18,8% | 1.032 | 832 | $114.662 |
| C. A + B | $10.779 | 0,19 | 16,1% | 1 | 753 | $99.408 |
| **D. mức dừng thảm hoạ 2×** | **$10.967** | **0,20** | 16,2% | **0** | **18** | **$639** |

**A cải thiện MỌI trục cùng lúc** — P&L ×3,5, Calmar ×2,7, sụt vốn giảm, phanh 1.072→0. Suốt
hai phiên chưa can thiệp nào làm được vậy. **Và A KHÔNG CÓ THAM SỐ** — không có gì để chọn nên
không curve-fit được. Đây là khác biệt căn bản so với mọi thứ đã thử.

**B vô dụng** một mình và **làm A xấu đi** khi ghép ($10.779 < $12.832).

**D đảo ngược kết luận hôm qua**: ở 1 hợp đồng nó trung tính về tiền; ở deploy nó cho $10.967
VÀ xoá 99,5% phụ thuộc vào ẩn số khớp lệnh (876→18 lệnh, $123.527→$639).

**BÀI HỌC LẶP LẠI LẦN THỨ HAI: kết quả 1 hợp đồng KHÔNG mang sang deploy.** Lần trước sai
theo hướng bất lợi (sửa điểm vào), lần này theo hướng có lợi (D). Từ nay mọi kết luận về can
thiệp phải đo ở tầng deploy.

Đang chạy: A và D trên hai vault (kỳ giữ riêng), và A+D ghép trên baseline.

### Bổ sung 2026-08-19 (lượt 3) — KỲ GIỮ RIÊNG BÁC BỎ CẢ A LẪN D

| | baseline IS | vault 2023-24 | vault 2025 (thật sự ngoài mẫu) |
|---|---|---|---|
| **mốc so: luật live + sửa khớp lệnh** | $3.716 · 0,09 | **$17.943 · 4,11** | **$4.998 · 1,11** |
| A. quét tới nến đúng chiều | $12.832 · 0,24 | $13.649 · 3,26 | $2.493 · 0,44 |
| D. mức dừng thảm hoạ 2× | $10.967 · 0,20 | $6.401 · 1,15 | $1.006 · 0,23 |
| A + D | −$2.313 · −0,05 | — | — |

**Cả hai tốt lên trong mẫu, xấu đi ở CẢ HAI vault.** Trên 2025 (kỳ duy nhất chưa từng thấy
dữ liệu): A còn một nửa mốc so, D còn một phần năm. A+D ghép lại âm.

**TỰ ĐÍNH CHÍNH:** lượt trước tôi viết *"A không có tham số tự do nên không curve-fit được"*.
Đúng kỹ thuật, sai kết luận. **Không có tham số tự do KHÔNG bảo đảm tổng quát hoá** — một
thay đổi luật vẫn là lựa chọn đưa ra sau khi đã nhìn dữ liệu, và vẫn hỏng ngoài mẫu. Bảng
trong mẫu rất thuyết phục (A cải thiện đồng thời mọi trục, phanh 1.072→0) và vault bác bỏ.

**KẾT LUẬN: không thay đổi gì.** Cấu hình tốt nhất trên cả hai vault vẫn là hệ hiện tại đo
bằng thước đã sửa. Khuyết tật điểm vào (46% nến resume sai chiều) và hình học stop (1/21,
42 ca sai phía) vẫn THẬT và vẫn nên ghi vào hồ sơ — nhưng mọi cách sửa đã thử đều không
sống sót qua kỳ giữ riêng.

### Bổ sung 2026-08-19 (lượt 4) — HAI KHUYẾT TẬT THỰC RA LÀ MỘT
`scratch/geom_after_A.py`. Sửa điểm vào (A) **tự sửa luôn hình học stop**, không đụng công
thức stop dòng nào — vì nến resume đúng chiều thì giá vào nằm sát chính cực trị mà stop neo vào.

| bộ tín hiệu | n | p01 | p10 | trung vị | p90 | stop sai phía |
|---|---|---|---|---|---|---|
| GỐC | 3.356 | **−0,052** | 0,395 | 0,777 | 0,961 | **42 (1,25%)** |
| **A** | 2.398 | **+0,503** | 0,716 | **0,887** | 0,977 | **2 (0,08%)** |

Đuôi âm biến mất · stop sai phía −95% · băng ATR bị ăn 22%→11% · phân tán rủi ro 6,0×→4,7×
· rủi ro/lệnh trung vị $33→$41.

**Và "stop hoàn hảo" thì tệ hơn**: C = A + ép stop neo vào giá vào cho $10.779/0,19 so với
A một mình $12.832/0,24. Sau A thì không còn khuyết tật để sửa; ép thêm lấy mất biến thiên
đang có ích.

**Không đổi kết luận:** A vẫn trượt kỳ giữ riêng (vault 2025: $2.493/0,44 vs mốc so
$4.998/1,11). Trong mẫu rất đẹp — P&L ×3,5, phanh 1.072→0, hệ sống đủ 7 năm thay vì chết
sau 2022 — ngoài mẫu không giữ.

### Bổ sung 2026-08-19 (lượt 5) — KIỂM PHÉP SỬA CÓ ĐẦY ĐỦ KHÔNG + gom tài liệu
`scratch/correction_complete.py`. Chỗ yếu nhất còn lại: phép sửa hậu kỳ chỉ chạm lệnh thoát
tại đúng bar vũ trang. Nếu còn trường hợp khác thì con số hiệu chỉnh thiếu.

| | tại bar vũ trang (đã chạm) | ở chỗ khác (BỎ SÓT) | nhãn GAP |
|---|---|---|---|
| quy ước engine | 591 lệnh · $38.904 | **26 lệnh · $120** (0,3%) | 133 |
| luật live | 645 lệnh · $99.502 | **1 lệnh · $0** (0,0%) | 100 |

Phần bỏ sót gần như toàn bộ là **làm tròn tick** (stop lẻ 4422,12 vs giá mở 4422,00 → $0,60).
Một ca thật duy nhất: MYM 13/03/2020, stop đã ratchet lên trong lúc giá rơi qua đêm COVID,
$110. **Nền của mọi con số hiệu chỉnh là vững.**

**ĐÍNH CHÍNH quan trọng — chuyện "45,9% lệnh vào sai":** tôi dán nhãn sai. Cái đo được là
*code lệch docstring*. Còn về giao dịch thì **không có bằng chứng nó gây hại, và có lý do cơ
học để tin nó CÓ LỢI**: bán khống ở nến tăng thì khớp ở giá cao hơn — giá vào tốt hơn. Lọc bỏ
chúng làm mất $7.256 ở deploy. **Thứ cần sửa là tài liệu, không phải code.** Hệ quả đáng chú ý
duy nhất là nó sinh ra hình học stop (42 ca stop sai phía).

### Đã gom thành `FILL_PRICING_AUDIT.md` ở gốc kho
Mười mục rời trong TASK.md có câu sai nằm xen câu sửa — ai đọc cũng lẫn. Tài liệu mới nêu
**trạng thái đã đúng**, mỗi khẳng định mang nhãn [ĐO] / [MÔ HÌNH] / [CHƯA KIỂM], kèm lệnh tự
kiểm. Từ đây đọc tài liệu đó, không đọc chuỗi mục này.

### Bổ sung 2026-08-19 (lượt 6) — QUÉT TRỤC STOP Ở TẦNG DEPLOY (15 cấu hình)
Giả thuyết: có một cách đặt stop cứu được hệ. Cơ chế đã xác định trước khi chạy: **circuit
breaker là ngưỡng** — cấu hình nào giữ sụt vốn dưới ngưỡng thì hệ không bị đóng cửa sau 2022
và có thêm hai năm giao dịch. Cam kết trước: chọn theo phanh=0 trước, P&L sau; đòi cao nguyên
±30%; chỉ sau khi chọn mới thử vault; vault xấu đi → đóng hướng.

Cổng mỏ neo PASS 4/4. Kỳ IS 2018-2024, deploy, 1 micro, 2-tick.

| cấu hình | net | Calmar | MaxDD | phanh |
|---|---|---|---|---|
| vũ trang 0h / 5h / 9,52h | −2.119 / −526 / −280 | ~0 | 17-18% | 925 / 1290 / 901 |
| vũ trang 12h / **14:05 live** / 16h / 20h | 1.826 / **3.716** / 2.961 / 2.680 | 0,04-0,09 | 19-21% | 1120 / 1072 / 916 / 894 |
| **thảm hoạ 2×** | **10.967** | **0,20** | 16,2% | **0** |
| **thảm hoạ 3×** | **13.600** | **0,27** | **14,7%** | **0** |
| thảm hoạ 5× / 8× | 2.557 / 2.653 | 0,06 | 19% | 788 / 1074 |
| stop 0,25 / 0,5 / 1,0 / 2,5 ×ATRngày | 3.554 / −1.705 / −3.082 / −230 | ~0 | 17-20% | 992 / 982 / 823 / 810 |

**Chỉ 2/15 đạt phanh = 0, và cả hai đều là mức dừng thảm hoạ.** Không giờ vũ trang nào, không
cơ sở ATR nào. Cơ chế được xác nhận: chỉ một lệnh dừng rộng NẰM SẴN TRÊN SÀN mới giữ được sụt
vốn dưới ngưỡng. Ở 3×: sụt vốn 14,7% — lần đầu tiên dưới trần cứng 15% trong hai phiên.

**Nhưng trượt hai trong ba cửa:**
- cao nguyên: ô kề 5× thấp hơn 81% → đỉnh nhọn. (Lưới nhảy 3×→5× là bước 67%, quá thô — ghi
  nhận nhưng KHÔNG nới quy tắc đã cam kết.)
- **kỳ giữ riêng: xấu đi ở CẢ HAI.**

| | baseline IS | vault 2023-24 | vault 2025 |
|---|---|---|---|
| mốc so | $3.716 · 0,09 | **$17.943 · 4,11** | **$4.998 · 1,11** |
| thảm hoạ 2× | $10.967 · 0,20 | $6.401 · 1,15 | $1.006 · 0,23 |
| thảm hoạ 3× | $13.600 · 0,27 | $10.721 · 1,73 | $3.750 · 0,80 |

**ĐÓNG HƯỚNG** theo cam kết.

**ĐÍNH CHÍNH lý do đóng hai trục kia:** trước đây tôi viết trục giờ vũ trang và trục stop "đã
đóng" dựa trên quét ở tầng 1 hợp đồng. Đo lại ở đúng tầng thì kết luận không đổi nhưng **lý do
khác hẳn**: ở 1 hợp đồng chúng phẳng vì không có cơ chế nào; ở deploy chúng hỏng vì không giữ
được sụt vốn dưới ngưỡng phanh.

### Bổ sung 2026-08-19 (lượt 7) — LẤP QUÃNG TRẦN: đóng, và lật giả thuyết của chính tôi
Giả thuyết: quãng trần tồn tại chỉ vì stop quá hẹp (1/21 dải ngày, 50% chạm trong 2 tiếng),
nên một stop rộng theo ATR ngày có thể đặt ngay từ lúc khớp — bỏ hẳn quãng trần.

**LỖI CÔNG CỤ tìm ra giữa chừng**: `run_loop` GHI ĐÈ tín hiệu từ sig_cache khi
`same_day_stop=True` — nhánh cache không `break` mà rơi vào vòng quét lại, sinh tín hiệu gốc.
Nên ba cấu hình đầu cho kết quả GIỐNG HỆT nhau. Sửa bằng cách bọc `generate_signal` ở tầng
chiến lược để cả hai đường cùng nhận. Chỉ ảnh hưởng lượt này; mọi phép đo trước dùng
`same_day_stop=False`.

Kết quả sau khi sửa (deploy, IS, cổng mỏ neo PASS 4/4):

| cấu hình | net | Calmar | MaxDD | phanh |
|---|---|---|---|---|
| **đối chứng**: stop hẹp, đặt ngay | −6.661 | −0,33 | 15,3% | 2.721 |
| stop 0,5×ATRngày, đặt ngay | −2.651 | −0,08 | 16,4% | 925 |
| stop 1,0×ATRngày, đặt ngay | −5.874 | −0,25 | 17,4% | 1.095 |
| stop 1,5×ATRngày, đặt ngay | −3.580 | −0,09 | 18,3% | 614 |
| stop 2,5×ATRngày, đặt ngay | −1.456 | −0,05 | 18,6% | 747 |

Ô đối chứng ĐẠT (tệ như dự đoán → cơ chế đúng, phép đo hợp lệ).
**0/4 đạt phanh=0, cả năm đều âm → ĐÓNG HƯỚNG theo cam kết.**

**GIẢ THUYẾT CỦA TÔI SAI.** Kể cả stop rộng gấp 20 lần đặt ngay từ lúc khớp vẫn cho −$1.456,
tệ hơn hẳn $3.716 của việc hoãn. **Khoảng ân hạn tự nó có giá trị**, không chỉ là chỗ né nhiễu
cho stop hẹp. Bất kỳ lệnh dừng nào sống trong ngày vào lệnh đều cắt mất phần lợi đó.

**Trục stop — bức tranh trọn vẹn, ba cách độc lập, đều đóng:**

| cách xử lý quãng trần | tốt nhất | phanh | vault |
|---|---|---|---|
| để trống hoàn toàn (hiện tại) | $3.716 | 1.072 | **4,11 / 1,11** |
| lấp bằng lệnh dừng thật từ lúc khớp | −$1.456 | 614+ | không tới bước này |
| hoãn stop chính + thêm lưới rộng (thảm hoạ 3×) | $13.600 | **0** | 1,73 / 0,80 — **hỏng** |

### Bổ sung 2026-08-19 (lượt 8) — PHANH: chốt cứng theo cấu tạo, nhưng KHÔNG phải đòn bẩy
Đọc code (`futures/circuit_breaker.py` + `deploy_sim.replay`): `peak_equity` chỉ tăng, không
bao giờ đặt lại; HALT chặn lệnh mới; đường thoát duy nhất là vốn hồi lên — mà muốn hồi thì
phải giao dịch. **Trạng thái hấp thụ.** `replay` tạo phanh một lần, không reset.

Đo lần HALT đầu: **ngày giao dịch thứ 811, vốn $53.716, sụt 15,2%** — đúng bằng vốn cuối kỳ,
tức nổ một lần rồi vốn đứng yên vĩnh viễn.

| | có phanh | không phanh |
|---|---|---|
| net | $3.716 | **$10.855** |
| Calmar | 0,09 | **0,10** |
| MaxDD | 19,2% | **31,6%** |
| 2022 / 2023 / 2024 | −4.893 / — / — | **−9.081 / +7.269 / +4.057** |

**ĐÍNH CHÍNH lượt trước:** tôi viết hệ "ngồi ngoài 2023–2025, giai đoạn lẽ ra kiếm $22.941".
Nói quá. Bỏ phanh thì 2023–24 được cứu (+$11.326) nhưng **2022 tệ đi gần gấp đôi**, và sụt vốn
lên 31,6%. Ròng: chốt tốn **$7.139**, đổi lấy **12,4 điểm sụt vốn**. **Calmar 0,09 vs 0,10 —
gần như không đổi.** Phanh không phá giá trị, nó đổi lợi nhuận lấy bảo vệ ~1:1.

Con số $17.943 của vault 2023-24 KHÔNG phải phản thực đúng cho "hai năm đó lẽ ra kiếm bao
nhiêu" — chạy liền mạch không phanh cho $11.326. Chênh do nhãn HMM khác và trạng thái vốn khác.

**HƯỚNG PHANH ĐÓNG.** Không có tiền bị nhốt ở đó.

### Bổ sung 2026-08-19 (lượt 9) — TRỤC ĐIỂM VÀO (ema) ở tầng deploy: đóng
| ema | 15 | 20 | 30 | 40 | **50** | 70 | 100 |
|---|---|---|---|---|---|---|---|
| net | −3.965 | −1.838 | 3.716 | 3.683 | **5.474** | 2.999 | 4.159 |
| Calmar | −0,14 | −0,05 | 0,09 | 0,09 | **0,12** | 0,06 | 0,09 |

Mở biên ra 70/100 thì đường quay đầu → cực đại ở 50 là **thật**, không phải hiện tượng rìa lưới.
**Nhưng trượt cửa cao nguyên**: ô kề 40 (−33%) và 70 (−45%), đều ngoài ±30%.

Vault: ema=50 cho **$16.197 · 2,18** (2023-24) và **$4.487 · 0,81** (2025), so với hiện tại
$17.943 · 4,11 và $4.998 · 1,11. **Xấu hơn cả hai → đóng.**

### TỔNG KẾT SÁU TRỤC — cùng một khuôn
| trục | tốt nhất trong mẫu | vault |
|---|---|---|
| giờ vũ trang stop (7 mốc) | $3.716 = hiện trạng | — |
| mức dừng thảm hoạ (4 mức) | $13.600 | hỏng 1,73 / 0,80 |
| lấp quãng trần từ lúc khớp (5 mức) | −$1.456 | không tới bước này |
| ema điểm vào (7 mức) | $5.474 | hỏng 2,18 / 0,81 |
| sửa hướng nến vào lệnh | $12.832 | hỏng 3,26 / 0,44 |
| phanh (chốt cứng) | +$7.139 nếu bỏ | Calmar 0,09→0,10, không phải đòn bẩy |

**Sáu cơ chế khác nhau, sáu lần cùng một kết cục: đẹp hơn trong mẫu, tệ hơn ngoài mẫu.**
Hiện trạng vẫn là cấu hình tốt nhất trên cả hai kỳ giữ riêng.

**CHƯA ĐỤNG:** ngưỡng gần EMA (0,5%), hai cổng khối lượng, cửa sổ vào lệnh 14:00–15:55,
và rổ công cụ.

### lượt 10 — kiểm định chính công cụ đo, trước khi tiêu vault

Yêu cầu: *"cần phải đảm bảo mô hình đúng tuyệt đối trước khi đốt vault"*. Kỳ 2026 đã chạy
nhưng **kết quả không được đọc** — cách ly tại `scratch/KHONG_DUOC_DOC_vault2026_chua_tieu.txt`,
chưa vào ngữ cảnh, vault vẫn nguyên.

**Lỗ hổng 1 — `run_loop` chưa từng có mỏ neo.** Cổng mỏ neo chạy với mọi cờ tắt, khi đó
harness gọi thẳng engine gốc; mọi kết quả có `arm`/`ratchet`/`stop_basis`/`disaster`/`entry`
lại đi qua `run_loop` mà không mốc nào chặn. Chạy `run_loop` ở cấu hình quy ước engine
(vũ trang 0h, ratchet bật, không sửa khớp), tầng deploy:

    net $42.459 · Calmar 1,72 · MaxDD 7,1% · phanh 0     ← trùng khít mốc ghim

**Lỗ hổng 2 — hiệu chỉnh có chảy vào cỡ vị thế và phanh không?** Ở tầng deploy giá thoát
nuôi vốn → cỡ lệnh sau → phanh. Bằng chứng đo được, có sẵn: bản chưa sửa **0 lần phanh**,
bản đã sửa **1.072 lần**. Phanh chỉ nhìn thấy vốn. Phép đo này có thể đỏ (hai số bằng nhau)
và nó không đỏ.

**Lỗ hổng 3 — soi từng dòng hàm hiệu chỉnh.** Ba giả định, kiểm cả ba:
- *loại giá*: `hl[ngày][2]` — xác nhận từ chỗ dựng cache là `(high, low, open, _isgap)`, đúng giá mở.
- *độ phủ*: điều kiện `d1 == d0 + 1 ngày lịch` bắt **941/1.025 (92%)** lệnh thoát sang ngày
  giao dịch kế tiếp. 84 lệnh còn lại là qua cuối tuần/lễ.
- *84 lệnh bỏ sót có sai không*: `_act = ngày vào + 1 ngày lịch + giờ` → thứ Bảy 14:05, mốc
  không tồn tại, nên mô hình vũ trang từ **nến đầu thứ Hai**. Sai chỉ xảy ra nếu thứ Hai mở
  cửa đã vượt stop. Đo: **0/84**. Đối chứng dương cùng logic trên nhóm 941 → **361 lệnh**,
  nên phép đo có thể đỏ.

Phụ phẩm, chưa định giá: **mô hình vũ trang lệnh cuối tuần từ nến mở thứ Hai, live vũ trang
14:00 thứ Hai** — mô hình cho không ~14 tiếng bảo vệ ở 8% số lệnh. Lệch mô hình/live thứ hai,
độc lập với lỗi giá khớp.

**Sổ kiểm định công cụ đo — trạng thái hiện tại**

| hạng mục | trạng thái |
|---|---|
| đường ống deploy_sim + engine gốc | neo chặt, 4 số ghim trùng khít |
| đường `run_loop` ở tầng deploy | **neo chặt hôm nay: $42.459 · 1,72** |
| bản sao vòng quét ≡ `build_sig_cache` | tự kiểm, 4/4 trùng |
| hiệu chỉnh chảy tới cỡ vị thế + phanh | đo được: phanh 0 → 1.072 |
| loại giá hiệu chỉnh về | xác nhận từ chỗ dựng cache |
| độ phủ hiệu chỉnh | 92% bắt; 8% còn lại đo ra không sai (đối chứng 361) |
| đầu ra đã sửa không còn khớp bất khả thi | 99,7% / 100% |

**Còn chưa kiểm**: nhánh `_roll_stop`; đường thoát của STRESS_MID (không có reconcile);
hành vi IBKR khi đặt STP vào thị trường đã đi qua (0 quan sát live); và lệch vũ trang cuối
tuần vừa phát hiện.

### lượt 11 — định giá lệch vũ trang cuối tuần (đóng)

Lượt 10 tôi báo "mô hình cho không ~14 tiếng bảo vệ ở 8% số lệnh". **Sai, và đây là số đúng.**

Đọc luật live (`runner.py`, quanh `_ARM_BY_CLUSTER`): live tính `mốc = ngày vào + 1 **ngày
lịch**`, rồi 14:00 New York. Vào thứ Sáu → **thứ Bảy 14:00 ET**. Đó là **đúng cùng công thức**
mô hình dùng. Không có lệch công thức nào cả; cả hai cùng cho ra mốc không tồn tại.

Lệch thật nằm ở chỗ khác và nhỏ hơn nhiều:
- **mô hình** vũ trang ở nến đầu tiên có thật sau mốc = **18:00 CN** (phiên mở lại)
- **live** vũ trang ở ca chạy đầu tiên sau mốc = **18:30 CN** (`stop_repair_sun_1830`,
  `run_scheduler.py` ~dòng 949; chú thích tại chỗ: "mở cửa + 30 phút cho phiên ổn định")

Khoảng hở = **30 phút**, không phải 14 tiếng.

Đo trên nhóm liên quan (Rổ 4, 1 hợp đồng, 2018-2024). Danh sách ngày của cache **có Chủ
Nhật** — phiên futures mở 18:00 CN — nên "ngày giao dịch kế tiếp" sau thứ Sáu là tối CN,
không phải thứ Hai. Cả 84 lệnh nhóm này đều là **thứ Sáu → Chủ Nhật**.

    lệnh thứ Sáu -> CN                          84
    đóng trong hở 18:00-18:30 (live chưa có stop) 41 (49%) = -$1.851
    đối chứng phân bố giờ đóng: 18h:45 19h:19 20h:10 21h:9 23h:1  (trải rộng, phép đếm lành)

**Kết luận**: lệch có thật, 41 lệnh, −$1.851 ở 1 hợp đồng trong 7 năm. Chưa đo ở tầng deploy.
Nhỏ, và **không phải lý do hoãn vault**. Bước 1 của kế hoạch lượt 10 khép lại ở đây.

**Bài học quy trình**: ba lần trong buổi này một số `0` hoá ra là tạo tác của chính phép đo
tôi viết — dò sai nến (mốc vũ trang), dò điều kiện không thể thoả (`k=1` nên nến 0 không bao
giờ là nến thoát), và so với giờ không có giao dịch (14:05 CN). Cả ba chỉ lộ ra khi cắm đối
chứng dương. Từ đây mọi phép đếm trong scratch phải có đối chứng bắn được trước khi báo số.

### lượt 12 — bất biến cho cấu hình không có mỏ neo

Mọi con số tiêu đề chạy ở `ratchet=False` + vũ trang 14,08h. Mỏ neo duy nhất nằm ở
`ratchet=True` + vũ trang 0h. Không neo được thì kiểm bằng bất biến, mỗi cái kèm đối chứng âm.

| | mệnh đề | chính | đối chứng âm |
|---|---|---|---|
| BT1 | không thoát trước mốc vũ trang | **0/1403 đạt** | 1530/1975 bắn |
| BT2 | ratchet tắt → thoát đúng stop ban đầu | **mẫu rỗng 0/0** | 0/0 → phép kiểm hỏng |
| BT3 | giá thoát trong biên độ nến (sau hiệu chỉnh) | 1/2018 | 629/2018 bắn |
| BT4 | ngày cầm ≤ 5, không âm | **0/2018 đạt** | — |

**BT2 lúc đầu chạy trên mẫu rỗng** — `_close` không mang `stop0` vào bản ghi lệnh. Không có
đối chứng âm thì tôi đã đọc "DAT" và tưởng đã xác minh ratchet. Lấy stop ban đầu từ bộ nhớ
tín hiệu thì ra 138/1383 lệch. Nguyên nhân **không phải mô hình sai**: vòng vào lệnh có điều
kiện `sig_cache is not None and exit_ts_today is None` — ngày nào vừa có vị thế thoát trong
chính ngày đó thì bỏ tín hiệu đã lưu và quét sinh lại tại chỗ, cho mức stop khác. Trung thành
với engine (mỏ neo $42.459 đi qua đúng đoạn này); bất biến viết sai.

**BT2 viết lại** — kéo theo chỉ nâng stop LONG, hạ stop SHORT, nên trên cặp lệnh khớp giữa
hai lần chạy giá thoát phải nằm về đúng một phía:

    cặp khớp 1.403 | hai bên khác nhau  1 | vi phạm 0  ĐẠT

**Phát hiện kèm theo, quan trọng hơn phép kiểm**: ratchet gần như là lệnh rỗng — 1/1403.
Cơ chế [SUY TỪ SỐ ĐÃ ĐO]: stop thực tế = 1/21 dải `mult × ATR ngày`, mà ratchet cập nhật bằng
`max(stop, đỉnh − mult×ATR_ngày)` nên vế sau gần như luôn thua. Hệ quả: chênh lệch live/backtest
ở khoản "live chưa cài ratchet" bằng 1 lệnh trên 1.403 — không đáng kể. Mặt yếu: đối chứng
BT2 chỉ bắn 1/1403 nên bằng chứng về nhánh ratchet là **yếu**, không phải mạnh.

**BT3 — lệnh vi phạm duy nhất**: M2K LONG vào 28/11/2018, thoát 30/11 lúc 07:02, ghi 1694,62
trong khi nến cao nhất 1694,60. Lệch 0,02 điểm = **$0,10**. Sai số làm tròn.

**Trạng thái công cụ đo**: cấu hình sinh ra mọi con số tiêu đề đã qua neo (một cấu hình),
bốn bất biến (ba có đối chứng mạnh, một yếu), kiểm dòng chảy hiệu chỉnh, và soi từng dòng hàm
hiệu chỉnh. **Chưa kiểm**: ba nhánh cờ chỉ dùng cho các trục đã đóng (`disaster`, `entry_mode`,
`stop_basis`) — không ảnh hưởng số nền, nhưng kết luận đóng trục thì có dựa vào chúng.

### lượt 13 — ba nhánh cờ của các trục đã đóng

| | mệnh đề | kết quả | đối chứng |
|---|---|---|---|
| BT5 | `stop_basis=x` → stop đúng bằng `x × ATR ngày` | trung vị **1,000×**, 0% sót mức hẹp | gốc 0,116× |
| BT6 | `entry_mode=wait` chỉ đẩy muộn hoặc bỏ ngày | 2.398 tín hiệu, **0** ngày lạ, **0** vào sớm hơn | 581 vào muộn hơn |
| BT7 | `disaster=k` → thoát đúng mức `vào ∓ k×|vào−stop0|` | 964 lệnh, 17 lệch → **17/17 giải thích được**, 0 còn lại | 0 rò rỉ khi tắt |

Hai lần trong lượt này con số xấu là do **phép kiểm** chứ không phải mô hình, và cả hai chỉ
tách ra được nhờ truy tới cơ chế:
- BT7 "17 lệnh sai mức": cả 17 có giá vào thật khác giá vào trong bộ nhớ tín hiệu → nhánh
  quét sinh lại. Tôi tra nhầm nguồn.
- BT5 "471/759 (62%) sai": đoạn bọc trong **tệp kiểm** lấy `a[0].index[-1]`, mà `a[0]` là
  Series nến nên `.index` là tên cột → ném lỗi → trả tín hiệu chưa sửa. `harness.py` bọc
  đúng chữ ký `(pullback_bar, resume_bar, …)` và lấy ngày từ `resume_bar.name`. Chạy lại
  qua chính đường harness: trung vị đúng 1,000× trên cả bốn mã, 0% sót.

Đối chiếu chéo tự khớp: gốc 0,116 × ATR ngày → `2,5/0,116 = 21,6`, trùng con số "stop thực
= 1/21 dải `mult × ATR ngày`" đo từ hướng khác trước đây.

**CÔNG CỤ ĐO — CHỐT TRẠNG THÁI**

Đã xác minh, mỗi mục bằng phép đo có thể đỏ: đường ống deploy (4 số ghim) · `run_loop` ở
deploy ($42.459) · bộ quét ≡ `build_sig_cache` · hiệu chỉnh chảy tới cỡ vị thế và phanh
(0→1.072) · loại giá và độ phủ hiệu chỉnh · BT1 vũ trang · BT3 giá trong biên độ nến
(1/2018 = $0,10 làm tròn) · BT4 ngày cầm · BT5/BT6/BT7 ba nhánh cờ.

Bằng chứng yếu, nói rõ: **BT2 ratchet** — 0 vi phạm nhưng đối chứng chỉ 1/1403, vì ratchet
gần như là lệnh rỗng. Đạt, nhưng không phải bằng chứng mạnh về nhánh đó.

Không thể xác minh từ bên trong: **luật khớp lệnh đã hiệu chỉnh có khớp hành vi thật của
IBKR hay không** — 0 quan sát live khi đặt STP vào thị trường đã đi qua. Đây là khoảng trống
thực nghiệm, không phải lỗ hổng code, và không đóng được bằng thêm backtest.

### lượt 14 — thử cấu hình: EMA 50 · stop 2×ATR ngày · vũ trang 14:05 D+1 · không ratchet · sửa khớp

Deploy, trong mẫu 2018-2024. Cấu hình hiện hành chạy cùng lượt làm cổng — tái tạo đúng $3.716.

| | net | Calmar | MaxDD | phanh | hiệu chỉnh khớp lệnh |
|---|---|---|---|---|---|
| hiện hành ema30, stop 2,5×ATR5 | $3.716 | 0,09 | 19,2% | 1.072 | 876 lệnh · $123.527 |
| chỉ ema=50 | $5.474 | 0,12 | — | — | 856 lệnh · $118.816 |
| chỉ stop 2,0×ATR ngày | −$75 | 0,00 | — | — | **7 lệnh · $779** |
| **cả hai (yêu cầu)** | **−$1.007** | **−0,03** | 18,9% | 724 | **6 lệnh · $746** |

Stop rộng là thành phần dập kết quả, không phải ema.

**Cơ chế** [ĐO]: `deploy_sim.real_risk` tính cỡ lệnh bằng `contracts × (mult × ATR NGÀY) × pv`,
không dùng `initial_stop` thật — nên `stop_basis` không đổi cỡ lệnh. Stop thật hiện hành
= 0,116 × ATR ngày → rủi ro thật bằng **4,6%** mức máy chia cỡ giả định. Đặt stop = 2,0 × ATR
ngày → **80%**. Cùng số hợp đồng, rủi ro thật mỗi lệnh tăng **17 lần**.

Không cứu được bằng cách giảm cỡ: Calmar chuẩn hoá theo quy mô và nó đi 0,09 → 0,00.

**Hàm ý**: kết quả dương của hệ phụ thuộc vào việc stop thực hẹp hơn ~20 lần so với thứ máy
chia cỡ tưởng đang dùng. Vá chỗ lệch đó thì lợi thế mất.

**Sai trong tài liệu code** [ĐO]: `deploy_sim.py` dòng 10-11 ghi cỡ lệnh dùng "the actual
initial stop distance, not a $500 stub". Sai — stop thật tính từ ATR 5 phút, chênh ~21 lần
so với ATR ngày mà hàm dùng.

**Mặt được có thật**: stop rộng làm khuyết tật khớp lệnh gần như biến mất (7 lệnh/$779 so với
876 lệnh/$123.527 = 0,6%). Quãng trần hết quan trọng. Nhưng giá phải trả lớn hơn phần cứu được.

Vault **không** đụng tới — trong mẫu đã âm thì không có ứng viên để đề bạt.

---
## Sub-task: Normal sleeve independent fill audit (2026-08-21)
Status: DONE (audit) / BLOCKED (deploy decision)

### Completed
- [x] scratch/normal_sleeve_fill_audit.py - strict fill/lookahead audit, 3 windows,
      re-assembly anchored to deploy_sim to the dollar in all three
- [x] Ro-4 CLEAN: 1,040 trades, 0 outside_exit_bar / outside_exit_day / signal_after_entry /
      same_or_before_bar_exit
- [x] NKD FAILS: 4 of 285 trades book an untraded price, all favourable, worth $8.57 total
- [x] Root cause measured (scratch/nkd_gap_mechanism_probe_20260821.py): gap-through test
      requires a >15-min TIME break; the failure is a 3-tick PRICE step between adjacent
      1-minute bars
- [x] Correction proven to be an engine-level rule change, not bookkeeping
      (scratch/nsfa_correction_equivalence_20260821.py): trade-for-trade identical
- [x] scratch/normal_sleeve_halt_probe_20260821.py - breaker/cushion decomposition,
      anchored to deploy_sim --no-nkd exactly (floor $8,570 / 354 halts)
- [x] Doc section appended to docs/futures/TF_REGIME_RESEARCH_2026-08-20.md, plus two
      corrections to earlier notes in that file
- [x] Trade tables persisted: scratch/normal_sleeve_trades_{floor,vault2025,vault2026}_20260821.json

### Key decisions
- Deploy-clean ON FILLS = Ro-4 + corrected NKD. NKD-original rejected (rule 1).
- Deploy-READY = neither. The blocker moved from the fill law to the risk layer.
- Floor +$33,176 decomposes: NKD edge +$3,898 (11.8%), breaker cushion +$20,708 (62.4%).
  The published +$33,181 is not the sleeve's edge.

### Next steps
- [ ] Fix the gap test in the engine and re-run the anchors (production change, not made)
- [ ] Decide what a HALT means - absorbing halt makes multi-year nets a function of one day
- [ ] Re-run floor cases cap075 / nkd_ema20 with halt count printed - are they latched too?
- [ ] Day-clustered bootstrap on NKD's floor +$3,898 before treating it as edge
- [ ] Settle rejection rule 4 on the floor window only (NKD helps headroom 1 of 3 windows)

### Files touched
scratch/normal_sleeve_fill_audit.py, scratch/normal_sleeve_halt_probe_20260821.py,
scratch/nkd_gap_mechanism_probe_20260821.py, scratch/nsfa_correction_equivalence_20260821.py,
docs/futures/TF_REGIME_RESEARCH_2026-08-20.md, SCRATCHPAD.md
(no production code changed, nothing committed)

---
## Sub-task: Normal promotion audit - R4 filter + NKD sleeves (2026-08-21)
Status: DONE (audit) / BLOCKED (promotion pending production patch)

### Completed
- [x] No-lookahead audit PASS: 4 instruments x 3 windows, features recomputed from a
      hard-cut frame, each check paired with a non-causal mutation that must fail
- [x] Regenerated the candidate from the SIGNAL PATH (filter inside generate_signal),
      not by deleting rows from saved trade JSON; anchors reproduce $33,176 / $6,857 / $6,743
- [x] Fill audit on regenerated books PASS (out_exit_bar / sig>entry / same_bar_exit /
      out_entry_bar_5m all 0); out_entry_bar_1m explained by 5m/1m aggregation
- [x] Portfolio replay, current cap vs strict025, 3 windows, with breaker headroom
- [x] NKD sleeve audit: fill equivalence on all 3 windows, slippage ladder + measured
      depth, centred cluster bootstrap, month-concentration
- [x] Doc section appended to docs/futures/TF_REGIME_RESEARCH_2026-08-20.md

### Key decisions
- Published candidate numbers ($34,109 / $8,537 / $8,313) are ROW DELETIONS. Honest
  regenerated figures: $33,970 Calmar 0.88 / $7,323 Calmar 1.61 / $8,675 Calmar 3.48.
- Verdict R4 filtered: PROMOTION CANDIDATE PENDING PRODUCTION PATCH.
- Verdict NKD: KEEP RESEARCH-ONLY (alpha not distinguishable from zero in any window).
- Keep the current cap; strict025 is rejected on measurement.

### Next steps
- [ ] Write and get approval for the engine patch (drop bool(isg[i]) from the gapped test
      in futures/_validated_core.py AND model_sameday_stop.run_loop), then re-run the
      INVARIANTS anchor gate - pinned numbers will move. NOT APPLIED.
- [ ] Re-select the filter by walk-forward folds; p90 threshold is in-sample on floor
- [ ] Settle entry-bar vs previous-bar rvol on floor evidence alone
- [ ] Live depth/spread sample for MNKD before NKD is revisited

### Files touched
scratch/normal_promotion_filter_lib_20260821.py,
scratch/normal_promotion_lookahead_audit_20260821.py,
scratch/normal_promotion_regen_audit_20260821.py,
scratch/normal_promotion_variant_matrix_20260821.py,
scratch/normal_promotion_nkd_sleeve_audit_20260821.py,
docs/futures/TF_REGIME_RESEARCH_2026-08-20.md, SCRATCHPAD.md
(no production code changed, nothing committed)

---

## Task: Stage 5X — dashboard/monitor audit + Track 1 explainability scaffold (2026-08-23)
Status: DONE (scaffold not wired; two questions open)
Scope: read-only against monitor/**; new files only in global_index/track1_explain.py and scratch/

### Completed
- [x] Audited all 13 monitor endpoints, 12 backend readers, 4 dashboard pages
- [x] MEASURED each reader's tolerance of unknown fields (event log tolerant; persisted
      positions is a 9-key allow-list and DROPS route/explain_id; paper evidence has no
      route split at all)
- [x] MEASURED what RAITS_TRACK1_SHADOW actually changes: only next_scheduled_job. The
      health slot table stays at 45 slots either way, so a Track 1 slot cannot raise an
      incident or move freshness
- [x] MEASURED the live decision block: runner initialises taken/rejected/halted/detail
      empty and never writes into them. 0 of 10 live snapshots carry any; 648 of 1749
      backtest replay snapshots do. Live rejections reach the screen only via a regex over
      a WARNING sentence in the day log
- [x] global_index/track1_explain.py — 5 record types, 38 rules, 34 reason codes imported
      (not retyped) from signal_layer/intraday/freshness, deterministic sha256 explain_id,
      validator, writer bounded to scratch/track1_shadow
- [x] scratch/test_track1_explain_20260823.py — 89 tests, 8 guards mutation-checked red
- [x] Schema + rule table GENERATED from the registry (gen_track1_explain_schema_*.py,
      gen_track1_rule_table_*.py), so neither can drift from the code
- [x] Tests: required pair 17 passed (baseline) -> 106 passed with the new suite;
      Stage 3/3B 113 passed 2 skipped. test_event_playback.py NOT run, as instructed

### Next steps
- [ ] OWNER DECISION: is the empty live decision block a design choice (rejections go to
      the log on purpose) or a wiring gap? Different fixes follow, and it decides whether
      Track 1 should ever populate the existing decision panel
- [ ] Call the record builders from the shadow route on a measured window, then MEASURE a
      day's record volume (deliberately unestimated — nobody has run it)
- [ ] Teach the health slot table about Track 1 behind the same env flag, or a Track 1
      slot failing at 11:05 stays silent
- [ ] Only then: route-scoped reader + endpoint. No legacy schema widened

### Files touched
NEW: global_index/track1_explain.py,
scratch/test_track1_explain_20260823.py,
scratch/track1_explainability_schema_20260823.json,
scratch/track1_dashboard_monitor_audit_20260823.md,
scratch/track1_explainability_design_20260823.md,
scratch/track1_dashboard_explainability_report_20260823.md,
scratch/gen_track1_explain_schema_20260823.py,
scratch/gen_track1_rule_table_20260823.py
NOT touched: monitor/** (all mtimes predate this session), runner.py, run_live_day_track1.py.
Nothing committed.

### Review round 1 (2026-08-23, owner) — validator hardened
- [x] Owner reported 3 validator gaps. All 3 reproduced. Probing the same family found 2
      more (extra code_ref for an uncited rule; forged evidence path) — 7 tamper cases
      total that validated CLEAN before the fix
- [x] Root cause was one thing, not seven: builder DERIVED explain_id / code_refs /
      evidence_refs and the validator never RE-derived them. Fixed by giving both sides one
      shared derived_refs(); comparison is on content not order, and that tolerance is
      itself pinned by a test
- [x] Chasing the route case found a BUILDER defect neither of us had named: route had two
      sources — the route= arg fed explain_id, and Identity.as_dict() was spread last and
      overwrote the field. A record could carry an id naming one route and a field naming
      another. Identity no longer emits route; builder REFUSES a disagreement
- [x] Confirmed the route check is NOT redundant with the id check: a record built
      consistently for route="legacy" produces an id that recomputes correctly
- [x] 6 new guards mutation-checked (12 assertions, all red when the guard is removed,
      all green when restored). Suite 89 -> 109; required pair 106 -> 126 passed;
      Stage 3/3B unchanged at 113 passed 2 skipped
- Revised verdict: write path is NOW ready to wire into run_shadow(). It was not before —
  wiring first would have written the first real explanations under a validator that could
  not tell a tampered record from an honest one, and those rows become the reference set.

---

## Task: Stage 5Y — wire explanation write path into the Track 1 shadow route (2026-08-23)
Status: DONE (write path wired; dashboard still not ready; 1 new open question)

### Completed
- [x] `explanations_for()` / `emit_explanations()` in run_live_day_track1.py; called from
      run_shadow() AFTER the decision file, from the SAME list in the same pass
- [x] Verdict->status/rules map is DATA and complete by test; an unmapped verb RAISES
- [x] File naming: option 1 — grouped by each record's OWN session_date, under
      scratch/track1_shadow/explanations/<window>/. Measured reason: vault2026 = 139
      decisions across 75 session dates, vault2025 = 183 across 104. Naming one file after
      the run date would repeat the scheduler_0809.log bug (file named for a date it does
      not contain)
- [x] MEASURED: 139/139 and 183/183 decisions->explanations, 0 invalid after re-read off
      disk, matched by identity tuple not just count
- [x] Legacy unchanged: run executed BOTH ways (explain on/off) into two roots; decisions,
      settlements and book_state byte-for-byte identical. Legacy fingerprint unchanged
- [x] Honest gaps counted, not faked: cluster_gross_after / family_gross / held_by_clusters
      travel as value=None with a `source` saying why; test fails if the count hits zero
- [x] Import test deliberately widened: run_live_day_track1.py allowed, legacy runner /
      scheduler / runner / 4 monitor readers forbidden, plus a sweep of the whole monitor
      tree and dashboard assets
- [x] 12 wiring mutations checked red, all restored green
- [x] Tests: required trio 127 passed; new wiring file 30 passed; Stage 3/3B 113 passed
      2 skipped (baseline). test_event_playback.py NOT run

### Key decisions
- write_shadow gained `mode` (truncate first batch per date): the decision file is opened
  "w", so append-only explanations would double on a re-run
- run_shadow gained `root` (relocates EVERYTHING it writes) so tests never write into the
  directory they audit
- fill_law read ONCE per run, shared by summary + checkpoint_report + explanation identity
- out_dir redirected outside the shadow root -> explanations SKIPPED with a visible reason
  in the summary (never silent, never a loosened bound). Route's own dir still raises

### New open question (NOT answered this stage)
- freshness verdict is computed on every shadow run, reported, and gates NOTHING.
  Measured: 91/91 (vault2026) and 128/128 (vault2025) accepted decisions carry a freshness
  proof that says FAILED, because the regime CSV was one session short. Bind it on live
  only / always / exempt replay? The records cannot choose.

### Files touched
NEW: scratch/test_track1_explain_wiring_20260823.py,
scratch/track1_explain_shadow_wiring_report_20260823.md
EDITED: global_index/run_live_day_track1.py, global_index/track1_explain.py (mode arg),
scratch/test_track1_explain_20260823.py (import test widened)
NOT touched: monitor/**, global_index/dash/**, runner.py, signal_layer.py.
Real scratch/track1_shadow NOT overwritten (parallel session active there).
Nothing committed.

---

## Task: Stage 5Z — freshness semantics + writer root contract (2026-08-23)
Status: DONE (freshness contract settled by measurement; root contract hardened)

### Completed
- [x] AUDIT: freshness is computed in run_shadow and binds NOWHERE. run_candidates has no
      freshness param; Track1Book.evaluate's `allow` is the BREAKER's verdict; OrderGate has
      zero references to freshness. The signal layer has no freshness refusal verb at all
- [x] CONTROL that settled it: same window, same code, three clocks. The SAME decision
      (explain_id t1x_80d87de4..., 2026-01-02, accepted) reads freshness passed=True at
      12:00 and passed=False at 15:00, with 91 accepted in every run. A field that moves
      while the thing it describes does not is run context, not proof
- [x] CONTRACT: replay = run context, never cited as proof. shadow_live/armed = binding,
      refuses to record an admission while the gate refused. All modes: an accepted
      decision may not carry ANY feature with passed=False
- [x] decision_mode is now a required field; schema bumped track1_explain/1 -> /2
- [x] ACCEPTED_PROOF_RULES_BY_MODE replaces the single tuple; the route DERIVES its set
- [x] New rule CONTEXT.FRESHNESS_OBSERVED + one run-context NO_ACTION record per run, so
      the reading is kept and correctly labelled instead of thrown away
- [x] MEASURED after: accepted_with_failed_proof 91 -> 0 (vault2026), 128 -> 0 (vault2025);
      accepted citing GATE.FRESHNESS = 0; decision stream unchanged at 139/183
- [x] ROOT: public resolve_shadow_dir(); no override flag exists and a test reads the
      signatures to prove it; 9 hostile destinations refused under a temp root
- [x] ZERO-DECISION: resolves destination and reports explanations_written: 0 explicitly,
      and still writes the run-context record
- [x] Stage 3/3B skips confirmed UNRELATED (TRACK1_EQUIV_FLOOR / TRACK1_REGEN, opt-in slow)
- [x] 11 mutations checked red, all restored green
- [x] Tests: required trio 128; 5Y wiring 30; 5Z new 45; Stage 3/3B 113 passed 2 skipped.
      test_event_playback.py NOT run

### Known limitation (stated, not hidden)
- The BINDING half is verified by construction (hand-built records per mode), never by a
  live run — the live source still refuses. "shadow_live binds freshness" = verified in
  code, unexercised in the wild until the live source produces a candidate.
- intraday_source is still reported `unverified` by the freshness gate every run. Separate
  gate, same shape of question, not settled here.

### Files touched
NEW: scratch/test_track1_stage5z_freshness_root_20260823.py,
scratch/track1_stage5z_freshness_root_contract_report_20260823.md
EDITED: global_index/track1_explain.py, global_index/run_live_day_track1.py,
scratch/test_track1_explain_20260823.py, scratch/test_track1_explain_wiring_20260823.py
COLLISION: run_live_day_track1.py is also being edited by Stage 5D (they added the live
slot path at 08:44). Edits made surgically; all 8 of their symbols verified intact after.
Real scratch/track1_shadow NOT written. Nothing committed.

## Task: Track 1 Stage 5Q — post-window / daily shadow audit as a scheduled job
Status: DONE (2026-08-24, ET session day 2026-08-24)
Scope: global_index/track1_shadow_audit.py (new), track1_shadow_acceptance.py (+scope API),
track1_slots.py (+audit job table), run_scheduler.py (+5 audit jobs, track1-only only),
monitor/backend/schedule_status.py (mirror), monitor/backend/track1_runtime_reader.py (+audits),
global_index/dash/realtime/realtime.js (Audit verdict row).

### Completed
- [x] Production audit runner: `python -m global_index.track1_shadow_audit --latest --all`
      (also --date / --sleeve / --from+--to / --dry-run). Writes ONLY to
      global_index/track1_runtime/audits/track1_audit_YYYYMMDD.jsonl, append-only, route-stamped.
- [x] Acceptance module gained scope, not rules: evaluate_sleeve, evaluate_day_audit,
      sleeve_slot_ids, windows_status(day=). No threshold restated anywhere.
- [x] Four verdicts: PASS / NOT_ENOUGH_DATA_YET / WARN / FAIL, with machine reason codes.
- [x] 5 scheduler jobs in track1-only-shadow: 03:05 NKD, 10:10 Calm, 12:40 Stress,
      16:05 Normal-R4, 16:15 daily. Times derived from WINDOWS_ET + a 10-minute buffer
      (close + 300s ceiling + 5 min margin). Inventory 95 -> 100; other modes unchanged
      (60 / 129); legacy strategy still 0; scheduler/mirror parity holds in all three modes.
- [x] Dashboard: /api/v1/track1-runtime carries an `audits` block; the panel shows an
      "Audit verdict" row that says "audit not run yet" in words. Absence is never a pass.
- [x] Tests: 67 new + 16/16 mutations detected (restores hash-verified). Regression:
      track1 scratch sweep 493 passed 1 skipped; monitor suites 295 + 31 passed.
- [x] Deliverables: scratch/track1_stage5q_post_window_audit_report_20260824.{md,json};
      appendices added to docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md and
      docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md.

### Not done / next steps
- [ ] OPERATOR: `python monitor\ops.py restart --backend` — brings the audits block and the
      pre-start classifier live. Does NOT schedule the audit jobs.
- [ ] OPERATOR: `python monitor\ops.py restart --scheduler --track1-only-shadow` — schedules
      the five audit jobs. Timing is the operator's call: a restart makes every window that
      already closed TODAY read as pre-start.
- [ ] First judgeable window: Tue 2026-08-25 01:10-02:55 ET (NKD, 22 slots), graded by the
      03:05 ET audit job.

### Key decisions
- Audit exit code is 0 on a FAIL verdict. A failing shadow window and a broken audit tool must
  not share one red light in the scheduler log; the verdict lives in the record.
- The scheduler hands the child its OWN start instant (--scheduler-started). The process-table
  probe fails to an empty list, and an empty list reading as "no scheduler" would turn a
  pre-start window into a manufactured incident.
- The audit prints its operational roll-up AND the committed daily acceptance gate verbatim,
  side by side. The stricter gate is never softened by the audit.

### Files touched
global_index/track1_shadow_audit.py, global_index/track1_shadow_acceptance.py,
global_index/track1_slots.py, global_index/run_scheduler.py,
monitor/backend/schedule_status.py, monitor/backend/track1_runtime_reader.py,
global_index/dash/realtime/realtime.js,
scratch/test_track1_stage5q_post_window_audit_20260824.py,
scratch/track1_stage5q_mutations_20260824.py,
scratch/track1_stage5q_post_window_audit_report_20260824.md/.json,
scratch/test_track1_stage5p_full_shadow_readiness_20260824.py,
scratch/test_track1_stage5p_operator_text_20260824.py,
scratch/test_track1_stage5m_d_track1_only_shadow_20260823.py,
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md,
docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md

### Safety statement
No scheduler started/stopped (pid 33868 unchanged), no backend restarted, no IBKR connection,
no order, no --allow-orders, TRACK1_ORDERS_APPROVED unset, no confirmation file, no live book
or checkpoint written, nothing written under global_index/track1_runtime/, no commit.

## Task: Track 1 Stage 5Q-1 — audit semantics (observed vs decided) + explanation path repair
Status: DONE (2026-08-24)
Scope: global_index/track1_shadow_acceptance.py, monitor/backend/track1_runtime_reader.py,
global_index/dash/realtime/realtime.js. track1_shadow_audit.py and run_scheduler.py UNCHANGED.

### Completed
- [x] Measured what a slot really writes (ran observe_live_slot into a temp tree, did not read
      it off a docstring): zero candidates already records decided=True. The brief's premise
      that "no_signal/no_candidate" was miscounted is WRONG; the miscounted one is the CLOCK
      refusal (too_early/too_late), which for NKD becomes 12 of 22 slots every winter.
- [x] Slot classification in the acceptance module: observed_decision / observed_no_action /
      observed_window_shut / observed_hard_refusal / unobserved. Fails closed.
      freshness_refused = HARD (it fires only when the engine ADMITTED while inputs refused).
      "too_late,stale" = HARD.
- [x] Window completeness is now observation-based; the ledger's decided-only verdict is
      reported beside it as `ledger_outcome` + informational reason `coverage_incomplete`.
- [x] REPAIR: the gate and the dashboard both read an explanation path NOTHING writes. The
      live writer nests under the window name (live_<date>/). Measured: 0 rows found. Both now
      resolve through acc.explanation_files; a test drives the REAL writer.
- [x] New FAILs: ledger row with no timing; timing with no ledger row (crash / mutex skip).
      Duplicates named, never fill a gap.
- [x] Quiet day: per-sleeve explanation requirement derived from the ledger's counters; the
      committed daily gate is reported verbatim and never forces the roll-up down.
- [x] Tests: 42 new; mutations 15/15 (5Q-1) + 16/16 (5Q re-run). Regression 565 passed 1
      skipped (track1 scratch, 16 files) + 305 passed (monitor, 5 files).
- [x] Deliverables: scratch/track1_stage5q1_audit_semantics_report_20260824.{md,json};
      correction note appended to the 5Q report (md+json); addenda in both docs/futures files.

### Blockers before Stage 5R
- [ ] B-5R-1 the live explanation writer opens the day's file with mode="w" on EVERY slot and
      all four sleeves share one file per session date, so only the last slot's rows survive.
      Not fixed here: truncate-on-seq-0 does not help (Stress 10:35 still erases Calm 10:00,
      same window name). Choice is per-sleeve window name vs append-only for the live path —
      an evidence-layout decision owned by the runner.
- [ ] B-5R-2 the freshness "proof" check is a substring match on the whole record; the context
      record carries no `proofs` key at all.
- [ ] B-5R-3 NKD after 2026-11-01: 12 of 22 ET slots fall outside the Tokyo decision band.
      Audit reports WARN, not FAIL. Whether the grid should follow Tokyo is a rule change.

### Operator
- No scheduler restart needed. The operator's 06:23 local restart already registered the five
  audit jobs (scheduler log: "5 Track 1 audit jobs registered", "Jobs (100)"). 5Q-1 changed
  only modules the audit CHILD imports fresh per spawn.
- Backend restart IS needed: `python monitor\ops.py restart --no-scheduler --track1-only-shadow`
  (CORRECTION: there is no `--backend` flag; the Stage 5Q report was wrong).
- First real audit: track1_audit_roska4_calm at 10:10 ET today (Calm IS judgeable — scheduler
  up at 08:23 ET). NKD today stays NOT_ENOUGH_DATA_YET.

### Safety statement
This session started/stopped NOTHING. Scheduler pid changed 33868 -> 6880 because the OPERATOR
restarted it between sessions. No backend restart, no IBKR, no order, no confirmation file,
nothing written under global_index/track1_runtime/ (audits dir still absent), no commit.

## Task: Track 1 Stage 5Q-2 — explanation evidence integrity
Status: DONE (2026-08-24)
Scope: global_index/track1_explain.py (layout owner + structured freshness rule),
global_index/run_live_day_track1.py (per-slot window + slot_id stamp),
global_index/track1_shadow_acceptance.py (delegates layout, structural check),
monitor/backend/track1_runtime_reader.py, global_index/dash/realtime/realtime.js.

### Completed
- [x] LAYOUT (Option B): each live slot owns a file at
      shadow/explanations/live_<date>/<sleeve>/<slot_id>/explanations_<daycompact>.jsonl.
      Truncation KEPT but scoped to the slot's own file — it is what stops a re-run doubling
      a slot's rows. Re-run semantics: replaces that slot's rows and nothing else.
      One owner: tx.live_window builds, tx.explanation_files finds, acceptance + dashboard
      delegate. Traversal refused, not sanitised. Replay path untouched (flat, by window).
- [x] FRESHNESS: structural rule in track1_explain (check_freshness_proof). Accepted+binding
      must cite GATE.FRESHNESS and carry a passed boolean feature; rejected owes it only if a
      cited rule declares it; every DECISION row must carry inputs_summary.freshness_allow as
      a bool; unrecognisable row fails closed.
- [x] 5Q-1 semantics preserved — whole 5Q-1 mutation harness re-run 15/15.
- [x] Dashboard shows rows + sleeves/slots per day; reader does NOT import the writer.
- [x] Tests 29 new; mutations 12/12 (5Q-2) + 15/15 (5Q-1 re-run) + 16/16 (5Q re-run).
      Regression 792 passed 2 skipped (21 track1 files) + 313 passed (6 monitor files).
- [x] Deliverables: scratch/track1_stage5q2_explanation_integrity_report_20260824.{md,json};
      corrections appended to the 5Q-1 report (md+json); addenda in both docs/futures files.

### Correction to 5Q-1
- The substring freshness check was too LOOSE only, not also too strict. My earlier probe used
  an empty inputs_summary; the real writer always fills freshness_allow. Recorded in the 5Q-1
  report as a dated correction.

### Blockers before Stage 5R
- [ ] B-5R-A (NEW, live-measured) the live frame cannot be spliced: frozen columns
      [open,high,low,close,volume] vs IBKR live [... ,average,barcount]. The 10:00 ET Calm slot
      crashed on it. Every sleeve hits it on every slot; no shadow day can be judged until the
      live fetch is projected onto the frozen columns. RUNNER lane.
- [ ] B-5R-B (NEW) SpliceRefused is not caught by observe_live_slot, so the slot writes no
      slot_observed row at all. The route's own rule is that the refusal is the record.
- [ ] B-5R-C NKD winter grid (carried, unchanged).
- [ ] B1 order gate (unchanged, intentional).
- [x] B-5R-1 writer truncation — CLOSED by this stage.
- [x] B-5R-2 substring freshness check — CLOSED by this stage.

### Operator
NO ACTION for this stage. Slots import modules fresh per spawn, so no scheduler restart.
Backend restart is cosmetic only: `python monitor\ops.py restart --no-scheduler --track1-only-shadow`
(verified: there is NO --backend flag).

### Safety statement
This session started/stopped nothing. The OPERATOR restarted the scheduler again (33868 ->
6880 -> 28696, now started 07:25:31 local = 09:25 ET). No backend restart, no IBKR connection
by me, no order, no confirmation file, all test writes under tmp_path, no commit.

## Task: Track 1 Stage 5Q-3 — live frame schema projection + auditable splice refusal
Status: DONE (2026-08-24)
Scope: global_index/track1_live_source.py (projection owner),
global_index/run_live_day_track1.py (catch SpliceRefused + wire slot_telemetry).
track1_live_frame.py and track1_shadow_acceptance.py UNCHANGED on purpose.

### Completed
- [x] PROJECTION OWNER = track1_live_source.live_frame, the ONLY caller of splice (asserted by
      a test that scans every production module). Order: fetch -> on_frozen_clock ->
      project_to_frozen_columns -> bars_from_the_future -> overlap_disagreement -> splice.
      Schema before prices.
      Rules: extras DROPPED (general rule, names carried on JoinedFrame.dropped_columns);
      missing frozen column REFUSED (missing_required_columns, never synthesised);
      NaN in a frozen column REFUSED (nan_in_required_columns). Column order from frozen.
      The guard stays strict so a caller that skips the projection is still caught.
- [x] SpliceRefused caught in observe_live_slot -> reason `live_frame_refused`, guard code in
      detail. Window still closes; no checkpoint for an incomplete window. Acceptance needed
      NO change (already classifies it observed_hard_refusal) - verified by test.
- [x] THIRD DEFECT FOUND: run_live_day_track1 had NEVER imported slot_telemetry. Wired.
      First Track1 timing rows ever: TRACK1_STRESS_1100..1115, ~2.7s, vs 240s target/300s ceiling.
- [x] Tests 32 new; mutations 10/10. Regression 903 passed 2 skipped (24 track1 files) +
      313 passed (6 monitor files).
- [x] Deliverables: scratch/track1_stage5q3_live_frame_splice_report_20260824.{md,json};
      correction appended to the 5Q-2 report (md+json); addenda in both docs/futures files.

### Correction to 5Q-2
- B-5R-A was ONE OF TWO live-frame blockers, not the only one. overlap_disagreement runs
  BEFORE the splice, so Stress (MNQ) never reached the column check and still refuses after
  the fix. Fixing the schema was necessary, not sufficient.

### Today's evidence
- TRACK1_CALM_1000 stays FAILED for 2026-08-24. Not rewritten, not migrated. Only slots
  spawning after the change pick it up - visible: 11:00 ET Stress slots are the first with
  timing rows.

### Blockers before Stage 5R
- [ ] B-5R-D (NEW, live) one MNQ history bar disagrees with the feed: 2026-08-21 13:45 ET,
      'low', history 29400.2500 vs feed 29395.7500, gap 4.5000, 1 of 1186 shared timestamps.
      Refuses every Stress slot; MNQ is in the swing basket too. DATA question, not code.
- [ ] B-5R-C NKD winter grid (carried).
- [ ] B1 order gate (unchanged, intentional).
- [x] B-5R-A live frame column mismatch — CLOSED.
- [x] B-5R-B SpliceRefused crashed the slot — CLOSED.

### Operator
NO restart of anything. Slots import modules fresh per spawn, so the fix is already live; the
dashboard reader is unchanged by this stage. If a refreshed UI is wanted for an earlier
stage's panel: `python monitor\ops.py restart --no-scheduler --track1-only-shadow`
(verified: there is NO --backend flag).

### Safety statement
Scheduler pid 28696 unchanged before and after; nothing started or stopped. No backend
restart, no IBKR connection by me, no order, no confirmation file, all test writes under
tmp_path, no strategy logic / order gate / job inventory change, no commit.

## Task: Track 1 Stage 5Q-4 — MNQ overlap audit, freshness gap, repair tool (dry-run only)
Status: DONE (2026-08-24). READ-ONLY on data. No parquet mutated.

### Measured (Part A)
- MNQ mismatch CONFIRMED: 2026-08-21 13:45 ET, `low` 29400.25 (parquet) vs 29395.75 (feed),
  gap 4.50, 1 of 1186 shared timestamps, 12 independent slot fetches agreeing over an hour.
  Evidence came from the route's OWN window-ledger rows — no broker query was made.
- The disputed bar IS the file's last bar (0 from end). `open` and `high` agreed exactly;
  `close`/`volume` were never compared (the guard raises on the first differing column).
- Direction: the feed's low is LOWER — the only direction a partial minute's low can be wrong.
- MECHANISM proven by code: update_ibkr_daily:548 `new_bars[... > last_existing]` = strictly
  newer, so the boundary bar is never revisited. Cannot self-heal. -> B-5R-F.
- Scope: MNQ disagrees. MES AGREES (the 10:00 Calm slot reached splice, and the overlap check
  runs before it, sorted order MES first). MYM/M2K first touched at 14:05; MNKD at 01:10.
- FAILED MEASUREMENT recorded as such: a volume-based probe cannot find partial bars. 13:45
  volumes span 5-20x naturally; the known-bad MNQ bar is NOT flagged (~0.9) while MYM's
  boundary bar IS (0.227). Historical frequency remains UNMEASURED.

### Measured (Part B) — B-5R-E, and it outranks B-5R-D
- preflight_state last day 2026-08-21 = true; spy_daily_live.csv last date = 2026-08-20.
- required_data_through(Mon 11:30 ET) = 2026-08-21 -> regime_csv STALE -> allow=False.
- update_spy_csv fetches through "today" at 13:45 ET, before the 16:00 close, so the CSV gains
  D-1 at D's preflight while the requirement jumps to D. One business day apart, permanently.
- The 13:45 preflight is the ONLY refresh in the schedule (read run_scheduler).
- shadow_live BINDS freshness => NO candidate can be admitted at any instant until settled.

### Part C — repair decision: Option 2, built, NOT applied
- scratch/track1_stage5q4_repair_boundary_bar_20260824.py, dry-run by default.
  --apply requires --expect <sha256>; snapshots first and re-reads the snapshot; bounds window
  and bar count; refuses on anything outside; refuses if the index would change; verifies by
  re-reading after the write.
- NOT applied because: only `low` compared; applying needs a broker fetch that would open a
  second client beside the Stress slots on clientId 89; and it fixes one day while B-5R-F keeps
  writing new boundary bars.
- Option 3 (drop the final parquet bar at runtime) REJECTED — it changes the frame every sleeve
  reads and would silently change frozen-window backtests.
- `_refuse_overlap_disagreement` NOT weakened (mutation N1 pins it).

### Tests
26 new + 9/9 mutations + 413 passed 1 skipped regression + 2 read-only probes.

### Blockers before 5R (ranked)
- [ ] B-5R-E freshness gate can never pass (largest).
- [ ] B-5R-D MNQ boundary bar (tool ready, not applied).
- [ ] B-5R-F update_ibkr_daily appends strictly-newer => a new partial bar every 13:45.
- [ ] B-5R-C NKD winter grid. [ ] B1 order gate (by design).
- [x] B-5R-A / B-5R-B closed by 5Q-3.

### Operator
NO action. Do not apply the repair yet; do not widen the overlap guard; no restart needed (no
production module changed). Two measurements arrive on their own: 14:05 ET (MYM/M2K) and
01:10 ET tomorrow (MNKD).
Safe read-only command after 12:30 ET:
  python scratch	rack1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ

## Task: Track 1 Stage 5Q-5 — D-1 freshness contract + boundary-bar appender
Status: DONE in code (2026-08-24). NOT fully live — see "what needs a restart".

### Part A — freshness (B-5R-E)
- Root cause: ONE requirement asked of TWO data sources with different availability.
  update_spy_csv runs at 13:45 and fetches through "today"; SPY closes 16:00, so it can never
  bring today's close — and the route does not need it: RegimeLabels.get = reg.asof(day-1).
- Design chosen = OPTION 1, split the requirement:
    required_intraday_through()      parquets — prev trading day, today from 13:45 (unchanged)
    required_daily_close_through()   daily CSV — the last TRADING day before today, all day
    required_data_through()          kept as a name, delegates to the intraday one
  Holiday-aware via raits.live.trading_calendar; calendar_source() reports which was used.
  Option 3 (split preflight_state) rejected: that file is written by the SHARED 13:45 job and
  read by legacy; the new consistency check surfaces the same information without touching it.
- NEW check `preflight_consistency`: names the case where the record says the 13:45 job
  SUCCEEDED and an input still does not satisfy the requirement. Silent when the preflight
  itself failed (retry vs contract question).
- MEASURED effect: the gate used to refuse 13:45 -> midnight EVERY trading day for a reason
  that was not true. It now allows there (~10 hours/day recovered). Monday morning still
  refuses, correctly: it needs Friday's close and the file holds Thursday's.
- Second half needs a JOB: `spy_refresh_pm` 16:20 ET mon-fri, update_spy_csv ONLY, no IBKR
  refetch, does NOT write preflight_state, a failure is NOT a preflight failure.
  Inventory 60->61 / 129->130 / 100->101, parity holds in all three, classified shared_infra.

### Part B — boundary bar (B-5R-F)
- `boundary_replacement()` in update_ibkr_daily: PURE (AST-tested), replaces the final stored
  bar only when the feed's version is a COMPLETION — open unchanged, low no higher, high no
  lower, volume no smaller — plus a 0.5% net. Refuses by name otherwise.
- The strictly-newer filter is UNTOUCHED; the replacement is concatenated between history and
  the new bars so ~duplicated(keep="last") prefers it. History invariant still holds for every
  other bar; the boundary timestamp is exempted BY NAME. Snapshot + verify-by-re-read.
- OFF by default (`--repair-boundary`). Today's 13:45 run is byte-identical to yesterday's.

### Part C — MNQ (B-5R-D) NOT repaired
  1) measure: python scratch	rack1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ
  2) repair (after approval): python -m global_index.update_ibkr_daily --repair-boundary --symbols MNQ
     (recommended over the scratch tool: same code that prevents recurrence; clientId 2)

### What is live now vs what needs a restart
- LIVE: track1_freshness.py (slots import fresh per spawn).
- NEEDS SCHEDULER RESTART: the spy_refresh_pm job (job defs fixed at make_scheduler time).
- NEEDS SCHEDULER EDIT + RESTART: --repair-boundary in the preflight argv.
- NEEDS BACKEND RESTART: the SPY_REFRESH_PM mirror row.
- While neither is restarted, scheduler and mirror agree, because neither has it.

### Tests
42 new + 16/16 mutations + 572 passed 1 skipped (14 track1 files) + 303 passed (5 monitor files).

### Blockers before 5R  => VERDICT NOT_READY
- [ ] B-5R-E refresh half — needs scheduler restart.
- [ ] B-5R-F — code done, OFF; needs scheduler edit + restart.
- [ ] B-5R-D — unrepaired; 2 commands above.
- [ ] B-5R-C NKD winter. [ ] B1 order gate (by design).

### Safety
Scheduler pid 28696 unchanged; nothing started/stopped. No IBKR connection, no order, no
confirmation file, no parquet/CSV/preflight_state mutated, all test writes under tmp_path,
overlap guard not weakened, no commit.

---

## Task: Stage 5Q-6 — operationalize the 5Q-5 freshness / boundary fixes on the live day
Status: DONE (stage) — VERDICT **NOT_READY for 5R**

### Completed
- [x] A. Live snapshot, read-only. Scheduler pid 28696 started 09:25 ET, mode
      track1-only-shadow, **100 jobs — spy_refresh_pm absent** (it started before the job
      existed). Backend pid 11720 fresh, mirror also lacks the row, so the two agree.
      Gate: blocking=['B1_broker_account_or_legacy_retirement'], orders_possible=False,
      confirmation=False, TRACK1_ORDERS_APPROVED unset.
      Evidence today: 52 coverage rows, 42 timing rows, 8 audit records.
      Timing p50 2.41s / p95 2.78s / max 3.27s, all outcome=ok, vs a 240s target.
- [x] Freshness verified LIVE and **ALLOWING**: csv 2026-08-21, required daily close
      2026-08-21, required intraday 2026-08-24, preflight_consistency ok. Goes stale tomorrow
      09:00 unless spy_refresh_pm runs at 16:20.
- [x] B. Boundary measurement, one read-only IBKR fetch on **client id 95** (clear of 89/90/1/2).
      MNQ 13:45 high +2.0 close +2.0 volume 738 to 1801 (open, low identical);
      MYM 13:45 volume 137 to 182; M2K 13:46 high +0.1 volume 2 to 15; MES clean;
      **MNKD REFUSED — 1052 bars disagree, first 2026-08-24 07:01 JST.**
      One preflight corrupts 3 of 5 instruments. Systemic and daily, not isolated.
      Friday's MNQ bar has fallen OUT of the fetch overlap — no longer measurable or
      repairable, still wrong in history, no longer causing refusals.
- [x] C. Repair decided (use the production appender) — **NOT applied**: the command was
      blocked by the environment's permission gate. Not worked around. Handed to the operator.
- [x] C-bis. Found and fixed a latent corruption in the 5Q-4 scratch tool: --apply wrote
      frozen_frame's tz-AWARE New York index back over a tz-NAIVE UTC parquet, i.e. it would
      have rewritten the storage convention of a 3.3M-row file. 26 green tests missed it
      because the fixture wrote a tz-aware parquet. Now restores the file's own convention,
      refuses column_shape_changed, re-verifies after writing, plus a naive-parquet test.
- [x] D. --repair-boundary **enabled** in the 13:45 preflight argv, on the measured
      recurrence above. All six conditions verified, including that a refusal appends to
      failed and sys.exit(1) makes the preflight FAILED rather than silently ok.
- [x] E. Restart NOT performed. Recommended tonight, before the 01:10 ET NKD window.
- [x] F. 13 suites, **472 passed**. Live audit dry-run: no false PASS, NKD correctly
      NOT_ENOUGH_DATA_YET, day verdict FAIL with every reason named.

### Next steps (operator, tonight, in order)
- [ ] python -m global_index.update_ibkr_daily --repair-boundary --symbols MNQ MYM M2K
- [ ] verify each of MNQ / MYM / M2K with the 5Q-4 repair tool in measure mode;
      each should print   verdict: nothing_to_repair
- [ ] python monitor\ops.py restart --scheduler --track1-only-shadow      (before 01:10 ET)
- [ ] python monitor\ops.py restart --no-scheduler --track1-only-shadow
- [ ] confirm 101 jobs / spy_refresh_pm 16:20 / SPY_REFRESH_PM mirrored / 70-11-5 /
      orders_possible=False with B1 still blocking
- [ ] **B-5R-G: audit MNKD's 1052-bar disagreement** the way MNQ was audited in 5Q-4.

### Key decisions
- --repair-boundary permanent because it was MEASURED to recur (3 of 5 instruments in one
  preflight; 46 slot refusals on Friday), not because the risk profile looked acceptable.
- Restart tonight, not tomorrow morning: today's windows are all closed AND audited, and a
  scheduler started this evening fully covers the 01:10 NKD window. Cost recorded — any
  future re-audit of 2026-08-24 reads its closed windows as pre-start; read the 8 written
  records instead. Nothing is deleted.
- MNKD is a NEW blocker (B-5R-G) and stays unexplained rather than being guessed at.

### Blockers before 5R  => VERDICT NOT_READY
- [ ] **B-5R-G (new)** MNKD 1052-bar disagreement — open, unmeasured, no command yet.
- [ ] B-5R-D/F recurrence — today's 3 partial bars unrepaired; one guarded command.
- [ ] B-5R-E refresh half — spy_refresh_pm not registered; needs the restart.
- [ ] B-5R-F prevention — --repair-boundary in argv in code, not in the running job table.
- [ ] B-5R-C NKD winter (WARN).  [ ] B1 order gate (by design; orders impossible).

### Files touched
global_index/run_scheduler.py (preflight argv);
scratch/track1_stage5q4_repair_boundary_bar_20260824.py (plus its test, plus the 5Q-5 test file);
scratch/track1_stage5q6_operationalize_freshness_boundary_20260824.md and .json (new);
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md; docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md.

### Safety
Scheduler pid 28696 and backend pid 11720 unchanged — nothing started, stopped or restarted.
ONE read-only IBKR fetch on client id 95, disclosed, zero orders, wrote nothing. No parquet,
CSV or state file mutated. No evidence row deleted or rewritten. Overlap guard not weakened.
No confirmation file. TRACK1_ORDERS_APPROVED unset. B1 still blocking. No commit.
Run 19:45-20:10 ET with every Track 1 window closed.

---

## Task: Stage 5Q-7 — apply the boundary repair, resolve MNKD, restart
Status: DONE (stage) — VERDICT **NOT_READY**; two blockers CLOSED, restart BLOCKED, one NEW blocker

### Completed
- [x] A. Pre-action snapshot. 20:17 ET, all windows closed, next 01:10. Scheduler pid 28696
      (09:25 ET, `--shadow-resume --track1-only-shadow`), **Jobs (100)**, `spy_refresh_pm`
      occurs **0 times** in the log; today's preflight argv logged verbatim as
      `-m global_index.update_ibkr_daily --port 4002` (no `--repair-boundary`); backend mirror
      `SPY_REFRESH_PM present: False`. Gate: B1 blocking, orders_possible=False.
      Evidence 52 / 42 / 8 rows; explanations dir absent (every slot refused).
- [x] B. **Boundary repair APPLIED** via the production appender, exit 0.
      MNQ 13:45 completed [close,high,volume]; MYM 13:45 [volume]; M2K 13:46 [high,volume].
      Alignment **median +0.0000, IQR 0.0000 over 2566 shared bars** — the boundary minute was
      the only disagreement. Each snapshotted and verified by re-read, history-check OK.
      Verified after: exactly those 3 files changed; MES and NKD byte-identical; snapshots only
      for touched files; index still tz-naive; columns unchanged.
- [x] B-declared side effect: the updater is an appender, so it also advanced each file ~335
      bars to 20:20/20:21 ET — stated before running.
- [x] **B-5R-H found (new).** The re-probe is NOT `nothing_to_repair`: the fetch stopped
      mid-minute and left a fresh partial bar. Measured through the real guard:
      MES ok, MNKD ok, **MNQ/MYM/M2K refuse on exactly 1 of ~1521 shared bars** at 20:20/20:21.
- [x] C. **B-5R-G CLOSED — MNKD was fetched as the ORDER symbol.**
      Two arms, same clock, read-only, client 95, same 1186 shared minutes:
      **MNK -> 1155 disagree** (worst 375, median-where-bad 25, signed close median **0.0**);
      **NKD -> 0 disagree** (worst 0.0000). Clock hypothesis REFUTED by magnitude, not count.
- [x] C-trap. `Contract.data_symbol` is the FILE STEM, not the fetch symbol (MES -> "ES").
      Using it would have sent all four basket instruments at the full-size E-minis.
      Fix derived from `_build_jobs` instead — the code that actually built the files.
- [x] C-fix. `update_ibkr_daily.history_ibkr_symbol()` + `track1_live_source.history_symbol()`;
      `IBKRBarProvider.fetch_session_bars` now fetches the history symbol.
      Orders unchanged (MNKD -> MNK). point_value unchanged (0.5 / 5.0). Guard unchanged.
      End to end: `live_frame("MNKD")` -> **code: ok, overlap_checked 1186, appended 341**.
- [x] C-live. `run_scheduler.py:1281` spawns each slot as a fresh subprocess, so the fix is
      **live tonight without a restart** — the 01:10 NKD window should be judgeable.
- [x] D. Restart **BLOCKED by the environment's permission gate**. Not worked around.
- [x] E. Audit dry-run: verdicts unchanged, 8 records intact, mtime unchanged, no false PASS.
- [x] F. 16 suites, **540 passed, 0 failed**; 16 new tests; **8/8 mutations red**.

### Next steps (operator, tonight, in order)
- [ ] `python monitor\ops.py restart --scheduler --track1-only-shadow`   (before 01:10 ET)
- [ ] `python monitor\ops.py restart --no-scheduler --track1-only-shadow`
- [ ] confirm 101 jobs / spy_refresh_pm 16:20 / SPY_REFRESH_PM mirrored / --repair-boundary in
      the preflight argv / 70-11-5 / orders_possible=False with B1 blocking
- [ ] tomorrow's audit: expect exactly ONE refusing bar per basket instrument (20:20/20:21).
      MES and NKD clean. More than one bar = new, stop.
- [ ] **B-5R-H:** its own stage — measure what dropping the in-progress minute costs, then
      change the appender. Do NOT run `update_ibkr_daily` off-schedule in the meantime.
- [ ] **B-5R-I:** legacy `fetch_bars("MNKD")` has the same symbol defect
      (`runner.py:1592`, `run_live_day.py:677`, `run_live_day.py:88`).

### Key decisions
- Repaired through the PRODUCTION appender, not the scratch tool: the appender concatenates
  onto the raw frame and runs `assert_utc_convention`, so it cannot make the convention
  mistake the scratch tool nearly made in 5Q-6.
- The MNKD fix reads `_build_jobs`, not `data_symbol` and not `_RAITS_TO_IBKR` — the authority
  is the code that fetched the files, and a second table is what caused the original incident.
- B-5R-H named and measured but NOT fixed tonight: it is a behaviour change to the shared 13:45
  job that also writes legacy's data.
- Stale tests repaired rather than deleted, each with the reason inline.

### Blockers before 5R  => VERDICT NOT_READY
- [x] ~~B-5R-G~~ MNKD symbol — CLOSED.   [x] ~~B-5R-D~~ boundary bars — CLOSED.
- [ ] **B-5R-H (new)** every append stores the in-progress minute.
- [ ] B-5R-E spy_refresh_pm / B-5R-F --repair-boundary — both need the blocked restart.
- [ ] **B-5R-I (new)** legacy route has the same MNKD symbol defect.
- [ ] B-5R-C NKD winter (WARN).  [ ] B1 order gate (by design; orders impossible).

### Files touched
global_index/update_ibkr_daily.py, global_index/track1_live_source.py;
DATA: NQ/YM/RTY `_continuous_1m_8y.parquet` (approved repair + ordinary append, snapshotted);
scratch/track1_stage5q7_mnkd_identity_probe_20260824.py,
scratch/test_track1_stage5q7_mnkd_identity_20260824.py,
scratch/track1_stage5q7_mutations_20260824.py,
scratch/track1_stage5q7_apply_boundary_restart_mnkd_identity_20260824.{md,json};
stale-test repairs in 5Q-5 / 5Q-3 / 5N test files;
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md.

### Safety
Scheduler pid 28696 and backend pid 11720 unchanged — not restarted (blocked). Three IBKR
connections, all disclosed: the approved repair on client 2, two read-only measurements on
client 95. Zero orders. MNKD and MES parquets byte-identical. No evidence row deleted or
rewritten. Overlap guard not weakened. point_value/multiplier untouched. No confirmation file.
TRACK1_ORDERS_APPROVED unset. B1 still blocking. No commit.

---

## Task: Stage 5W — the paper executor skeleton, uncalled by production
Status: DONE — verdict READY_FOR_PAPER_EXECUTOR_WIRING (2026-08-25)

### Completed
- [x] `global_index/track1_paper_executor.py` — the entry path, assembled from 5T mapping,
      5U contracts and the 5V journal. Fail-closed: intent and attempt both durable before the
      broker is called, both raise, ambiguity records UNKNOWN and re-raises.
- [x] It never writes the route's book — no writer in the file at all, proved by AST.
- [x] `read_book` fails closed, and reads the key the real writer writes (`qty`, measured from
      `track1_bootstrap.snapshot_book` — my first version asked for `contracts` and would have
      refused every genuine book while looking safe). Refuses another route or another schema.
- [x] `broker_capability_report` / `INTERIM_UNKNOWN_RESOLUTION` — the two missing IBKRBroker
      methods named as data, with a test that fails the day someone adds one.
- [x] Three walls, each tested: refuses an unarmed gate (against the real blocker table),
      imported by nothing, and the slot path takes no order argument.
- [x] Arming changes the recorded label and nothing that decides — proved structurally.
- [x] 52 tests, 18 mutations all red. Regression 234 + 95 passed.
- [x] Deliverables: `scratch/track1_stage5w_paper_executor_20260825.{md,json}`, Stage 5W
      section in `docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md`.

### Corrected while doing it
- Stage 5V-1 reported "nineteen slots hard-refused"; the closed ledger says **21** (20
  `partial_coverage,stale` + 1 `stale`, plus 1 benign `too_late` = 22 rows). Written mid-window
  and undercounted. The test now pins the distribution exactly instead of as a subset.
- 5U and 5V asserted their modules were imported by nothing; the executor now imports all three,
  so both suites assert the head of the chain is unimported instead — and were upgraded from
  substring scans to AST.

### Next steps
- [ ] Do NOT wire the call site yet. It is one line in `run_shadow` (line 1062, where
      `NoOrderBroker()` is constructed) and it is the line that makes orders possible.
- [ ] `PAPER_SHADOW_EVIDENCE` needs 5 judgeable days and has 0. First NKD window that can be
      judged on the fixed gate: **2026-08-26 01:10 ET**.
- [ ] `spy_refresh_pm` fires for the first time 2026-08-25 16:20 ET — a different gate, not yet
      observed working.
- [ ] `close_position` / `place_protective_stop` / `switch_same_symbol` are still 5T stubs.

### Key decisions
- One operation only. Building all four before the first has been watched run would be three
  more things to unwind.
- The executor requires an ARMED gate at CONSTRUCTION, not per call, so an unarmed executor
  cannot exist to be called by mistake.
- Ambiguity is UNKNOWN, never REJECTED. "No" and "I could not hear you" are different facts.
- Proved arming by AST rather than a two-arm run: a run-and-compare proves the two modes agreed
  on the day it ran; the structural proof covers every day.

### Files touched
global_index/track1_paper_executor.py (new), global_index/track1_paper_order.py,
scratch/test_track1_stage5w_paper_executor_20260825.py,
scratch/track1_stage5w_mutations_20260825.py,
scratch/test_track1_stage5u_order_state_reconcile_20260825.py,
scratch/test_track1_stage5v_order_journal_20260825.py,
scratch/test_track1_stage5v1_intraday_causality_20260825.py,
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

---

## Task: Stage 5X — broker read side and Track 1 reconcile readiness
Status: DONE — verdict READY_FOR_PAPER_ORDER_CALLSITE_DESIGN (2026-08-25)

### Completed
- [x] `global_index/track1_broker_read.py` — tri-state reads (KNOWN / UNKNOWN) over any broker.
      Pure, no ib_insync, no ibkr_broker import, imported by nothing.
- [x] `resolve_submitted()` — the seven cases. REJECTED is reachable ONLY from a broker
      statement; silence (NOT_FOUND / empty / None / raised) is never rejection.
      Question order: working orders, then status, then execution; POSITIONS LAST and never
      decisive alone.
- [x] `IBKRBroker.get_open_orders()` — additive, called by nothing, `None` offline and `[]` for
      "book clear", not filtered by clientId. Thin read over `reqAllOpenOrders()`, which the
      file already called at 5 sites.
- [x] `NoOrderBroker.CAN_TESTIFY = False` — marker only; its `[]` return is unchanged because
      several suites depend on it.
- [x] Exits narrowed: allowed under UNKNOWN/MISMATCH **only if they reduce exposure**.
- [x] Book read-back confirmed: `qty` (pinned against the writer's source), missing = empty
      book, corrupt = fail closed AND blocks entries at the call site.
- [x] 52 tests; 20 mutations all red; combined regression 546 passed across 21 files including
      the 10 legacy IBKR suites.
- [x] Deliverables: `scratch/track1_stage5x_broker_readside_20260825.{md,json}`, Stage 5X
      section in `docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md`.

### Corrected while doing it
- **Stage 5W's `MISSING_BROKER_METHODS` was wrong on both entries.** `get_executions` was a
  name nobody proposed — the capability exists as `find_execution(order_id, inst)`.
  `get_open_orders` was absent as a method but the underlying call was already used 5×.
  The real surviving gap is that `broker.Fill` carries **no order id**.
- **The mutation harness could report a false RED.** pytest exits non-zero on an unknown test
  id, so a renamed test read as a successful mutation. `expect_red` now proves each test green
  BEFORE mutating. Two mutations were also unfaithful (`Path.read_text` patch vs
  `inspect.getsource` linecache).
- 5U's wiring test: the chain now has TWO heads (executor + read module); both must stay
  unimported.

### Explicitly NOT done (and why)
- The three legacy readers (`get_positions`, `get_order_status`, `find_execution`) were **not**
  modified. `runner.py` B3/B4 is built on today's answers; `test_42` reads the file and turns
  red if anyone "fixes" them.

### Next steps
- [ ] Do NOT wire the call site. Still one line in `run_shadow` (`NoOrderBroker()`).
- [ ] `PAPER_SHADOW_EVIDENCE`: 0 of 5 judgeable days. First fixed-gate NKD window
      **2026-08-26 01:10 ET**.
- [ ] Stage 5Y candidate: make `send_order` return an order id. That is a WRITE-path change and
      would retire the weaker working-orders-then-positions fallback.
- [ ] `close_position` / `place_protective_stop` / `switch_same_symbol` still 5T stubs.

### Key decisions
- Re-label above the legacy reads rather than repair them — the same collapse is conservative
  for legacy and dangerous for Track 1.
- Follow the convention already stated in `broker.py` (`None` = cannot say) instead of
  inventing one.
- Positions never resolve an order on their own.

### Files touched
global_index/track1_broker_read.py (new), global_index/ibkr_broker.py,
global_index/run_live_day_track1.py, global_index/track1_paper_executor.py,
scratch/test_track1_stage5x_broker_readside_20260825.py,
scratch/track1_stage5x_mutations_20260825.py,
scratch/test_track1_stage5w_paper_executor_20260825.py,
scratch/test_track1_stage5u_order_state_reconcile_20260825.py,
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

---

## Task: Stage 5Y — broker order-id write path
Status: DONE — verdict READY_FOR_PAPER_ORDER_CALLSITE_DRY_RUN_DESIGN (2026-08-25)

### Completed
- [x] `Fill.order_id` — appended LAST, default `None`. No `asdict`/`astuple` caller exists,
      so nothing serialised moved; positional/keyword/mixed construction all unchanged.
- [x] `OrderReceipt` + `on_submit` (KEYWORD-ONLY, default `None`) on the ABC, MockBroker and
      IBKRBroker. Fires between `placeOrder` and the fill poll — the 30s window is the whole
      reason it exists. 7 of 8 `Fill` returns carry the id; the 8th is test mode, which places
      nothing and invents nothing.
- [x] `OrderReceiptRefused` re-raised past `send_order`'s broad handler, so a LIVE order can
      never be reported as `Fill(status="CANCELLED")`.
- [x] The `except` path now separates "never reached the broker" from "reached it and then
      threw" — the second leaves live exposure.
- [x] Journal amendment: `SUBMITTED -> SUBMITTED` permitted ONLY as the arrival of the id.
      Narrow (no replacement, no empty, no other field moves) so a duplicate send cannot look
      lawful. `BAD_AMENDMENT`.
- [x] Read side: the id is authoritative INCLUDING negatively — a different id is not ours and
      the instrument+action fallback is not consulted afterwards.
- [x] 58 tests; 24 mutations all red; combined regression **620 passed** across 26 files
      including the 16 legacy Fill/send_order consumers. `test_event_playback.py` not run.
- [x] Deliverables: `scratch/track1_stage5y_order_id_writepath_20260825.{md,json}`, Stage 5Y
      section in `docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md`.

### The bug this stage shipped and fixed
`append` accepted the amendment; `resolve` then called the resulting journal an impossible
history. **Every order that got an id would have made that day's journal unreadable.** All 52
tests passed over it — they checked the write, none re-read. Found by running the round trip by
hand. Fix: ONE shared rule, `track1_order_state.is_amendment`, used by `resolve_journal` and
asserted by the writer. Six read-back tests added.

### Harness lessons (again)
- Seven mutations were source patches against BEHAVIOUR tests. `_source_patch` only changes
  `Path.read_text`; it cannot alter an imported function. Stage 5V M3 lesson, repeated twice
  more in one session.
- One patched `broker.Fill` while the test did `from ... import Fill` — the name was already
  bound in the test module.
- M17 was faithful and found a real hole: an unparseable file was `continue`d over, so the test
  passed while a legacy call site had changed. Now a reported failure.

### Next steps
- [ ] Do NOT wire the call site. Design it as a DRY-RUN mode first: build the executor, refuse
      at the broker boundary.
- [ ] `PAPER_SHADOW_EVIDENCE`: 0 of 5 judgeable days. First fixed-gate NKD window
      **2026-08-26 01:10 ET**.
- [ ] `close_position` / `place_protective_stop` / `switch_same_symbol` still 5T stubs.
- [ ] `perm_id` is carried but never waited for (usually 0 at placement). A stable global id
      would be a second read, not a longer wait.

### Key decisions
- BOTH a Fill field and a placement receipt. Neither alone survives a crash during the poll.
- Additive-only: keyword-only argument, field appended last. Legacy readers untouched.
- A missing id is never invented. A fabricated identifier is worse than none because a
  reconcile trusts it.

### Files touched
global_index/broker.py, global_index/ibkr_broker.py, global_index/track1_order_state.py,
global_index/track1_order_journal.py, global_index/track1_paper_executor.py,
global_index/track1_broker_read.py,
scratch/test_track1_stage5y_order_id_writepath_20260825.py,
scratch/track1_stage5y_mutations_20260825.py,
scratch/test_track1_stage5w_paper_executor_20260825.py,
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

---

## Task: Stage 5Z — paper order callsite dry-run design
Status: DONE — verdict READY_FOR_PAPER_CALLSITE_IMPLEMENTATION_AFTER_EVIDENCE (2026-08-25)

### Completed
- [x] `global_index/track1_paper_callsite.py` — NEW, imported by nothing, cannot send.
      Six stages: gate · reconcile_precheck · executor · mapping · journal · boundary.
- [x] `seam()` DERIVES the call-site location from the file and refuses when ambiguous.
- [x] `RefusingBroker` — the wall. Silent in two independent ways.
- [x] `assert_dry_run_root` — refuses the production journal, any parent, any child.
- [x] A dry run succeeds by being STOPPED: `ok` requires `reached_boundary`.
- [x] 44 tests; 23 mutations all red; combined regression **695 passed** across 27 files.
- [x] Deliverables: `scratch/track1_stage5z_callsite_dryrun_20260825.{md,json}`, Stage 5Z
      section in `docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md`.
- [x] **No production file was modified.**

### The correction Stage 5W owed
5W called `run_shadow`'s `NoOrderBroker()` line "the call site". Both halves wrong:
`run_shadow` replays a measured WINDOW and is not what the scheduler runs (the 70 strategy
slots run `observe_live_slot`), and in `run_shadow` the broker is **never passed to anything** —
constructed, then read once for `len(broker.calls)`. Swapping it would change nothing.
Real seam: `observe_live_slot`, right after `settlements, decisions = run_candidates(...)`.

### Stub scope — DECIDED: entry only
Measured from the scheduler registry, not judgement:
- protective stop + max-hold exit are **already covered** — 11 Track 1 safety jobs against
  `live_positions.track1.json`, B3/B4 inside `FuturesRunner.__init__`;
- they no-op ONLY because the book file does not exist;
- **so the first paper fill activates eleven jobs that have never run against anything**, and
  they connect to IBKR. Watch that, do not discover it.
- `track1_switch` is imported by NOTHING, so it cannot bypass the journal.
- Known gap, named: stops/exits from the safety jobs write `trade_log`, NOT the order journal.

### Chain head: two doors became one
5X left two heads (executor + read module). 5Z's dry run imports both and nothing imports it —
one door to watch. Five tests in 5U/5V/5W/5X/5Y updated to assert exactly that.

### Mutation finding
M6, M10, M11 stayed green because the CODE is right twice: `ok` is guarded by the property AND
the boundary stage's own flag; the wall both declines to testify AND returns cannot-say values.
Both redundancies are now pinned (`test_7b`, `test_24b`) and the mutations remove both guards.

### Next steps
- [ ] `PAPER_SHADOW_EVIDENCE`: 0 of 5 judgeable days. First fixed-gate NKD window
      **2026-08-26 01:10 ET**.
- [ ] `B1_broker_account_or_legacy_retirement` — user decision.
- [ ] Implement the call site ONLY after evidence, entry-only, at the derived seam.
- [ ] Later: route safety-job stops/exits through the executor so they reach the order journal.

### Files touched
global_index/track1_paper_callsite.py (new),
scratch/test_track1_stage5z_callsite_dryrun_20260825.py,
scratch/track1_stage5z_mutations_20260825.py,
scratch/test_track1_stage5u/5v/5w/5x/5y_*.py (chain-head assertion),
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md, TASK.md

---

## PENDING — Post-stage causal seam audit (raised 2026-08-25, Stage 5W)

**Do not do this yet.** It runs AFTER the Track 1 shadow/paper plumbing stages are complete,
and it is mandatory before paper orders.

**What:** sweep for replay and full-day tests that never exercise a PARTIAL live slot — that
is, a moment mid-window when only part of the session exists yet. Stage 5V-1 is the reason:
the NKD intraday gate demanded bars to the end of the band for every slot, and every offline
test passed because every offline test handed it a WHOLE session. Nineteen live slots were
refused before anyone saw it. A second bug hid in the same blind spot — the staleness horizon
compared a five-minute grid against a continuous `now` and failed by the three seconds a slot
takes to start.

**Where to sweep, at minimum:**

```text
intraday gates           track1_intraday       today_span / staleness / decision_bar
freshness gates          track1_freshness      required_* horizons at mid-session instants
session clocks           ET vs Asia/Tokyo, and the DST drift between them
resampling               run_live_day_track1._resample and its bucket-boundary behaviour
live source joins        track1_live_source    splice, overlap, projection at a partial tail
scheduler argv/env       run_scheduler         what a slot is actually launched with
ledger + audit readers   window_ledger, track1_shadow_acceptance, track1_shadow_audit
dashboard readers        monitor/backend/*     mid-window vs closed-window states
order + reconcile path   track1_order_journal, track1_order_state, the executor
```

**The test to write for each:** the same input at N different instants inside the window, not
one input at the end of it. A gate that only ever sees a finished session is a gate nobody has
tested.

### Files touched
TASK.md (this note).

---

## Task: Stage 5ZA - post-stage causal slot audit
Status: DONE - verdict READY_FOR_NEXT_SHADOW_WINDOW_WITH_CAUSAL_SLOT_GUARD (2026-08-25)

### Completed
- [x] Added `scratch/test_track1_stage5za_causal_slot_audit_20260825.py`.
- [x] Swept all 70 Track 1 strategy slots with synthetic frames containing only the bars each
      slot is causally allowed to require. No slot now demands the end of its window/session.
- [x] Found and fixed a new live blocker: `TRACK1_CALM_1000` passed at exactly `10:00:00` but
      refused `too_late` at `10:00:01`. The gate now has a 60-second dispatch grace: a few
      seconds late is still the scheduled slot; past grace is still fail-closed.
- [x] Re-pinned 5V-1: final scanning-window slots are allowed inside dispatch grace, and
      `too_late` remains classified as observed-window-shut when genuinely late.
- [x] Static seams pinned: every live-source sleeve fetches `through=now`; Stress and
      Normal/NKD detectors truncate to the slot instant; Calm uses the entry-only detector,
      not the full-day replay; the paper callsite seam is `observe_live_slot`, not `run_shadow`.

### Still pending for operational audit
- [ ] Full mutation pass for 5ZA. The direct tests are in place and caught one production
      defect; mutation proof is still worth doing before paper.
- [ ] Runtime verification after the next judgeable window: audit row PASS/FAIL, timing rows,
      explanation rows, and no phantom dashboard overdue row.
- [ ] First-paper safety watch remains: the first paper fill will activate 11 Track 1 safety
      jobs that have never protected a real Track 1 book.

### Files touched
global_index/track1_intraday.py,
scratch/test_track1_stage5za_causal_slot_audit_20260825.py,
scratch/test_track1_stage5v1_intraday_causality_20260825.py,
scratch/track1_stage5za_causal_slot_audit_20260825.md,
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md,
TASK.md.

---

## Sub-task: STOCKS-0 — backtest tuyến cổ phiếu từ logic ứng viên Track 1 (2026-08-26)
Status: DONE (đo xong, chỉ đọc, không commit, không chạm mã sản xuất)

Phạm vi tệp: chỉ `scratch/stocks_stage0_*`. Không sửa `global_index/**`, `futures/**`,
`monitor/**`, `raits/**`. Không kết nối broker. Không đặt lệnh.

### Phán quyết
- BACKTEST_VALID / **NO_EVIDENCE_OF_PORTABLE_EDGE** (cổng cam kết trước, 2/3 điều kiện trượt)
- Cấu hình chính: Normal-R4 + cổng SHORT theo SPY, nhãn HMM nhân quả lag 1, ema 50,
  75 mã, RTH 5 phút, 2019-01-02..2022-12-30
- Ròng +$9.282 trên $100k trong 3,9 năm (CAGR 2,3%), PF 1,08, sụt tối đa $19.900
- **Ngoài mẫu 2021-2022: −$2.324, p=0,58** (bootstrap gom cụm theo ngày, null căn giữa)
- Trượt giá hoà vốn 7,38 bps/chiều (đạt ngưỡng ≥6,0 — điều kiện duy nhất đạt)
- Cửa sổ 5 năm 2018-2022 (nhãn sản xuất, nhìn trước ở tầng nhãn): ròng +$3.672, PF 1,02,
  ngoài mẫu −$3.102; riêng 2022 −$11.798

### Ràng buộc dữ liệu đã đo
- Bar 5 phút cổ phiếu: 2017-01-03..2022-12-30, 75 mã. **2023/2024/2025/2026 = 0 phiên-mã.**
- 1,9 GB dữ liệu 1 phút Databento chỉ có 09:30-10:44 ET → không dùng được cho cửa sổ 14:00-15:55
- Không có rổ theo thời điểm trên đĩa → kết quả thiên lệch sống sót, không sửa được
- META chỉ 290/1008 phiên (đổi mã, không có FB trong cache); LOW 797; SBUX 970

### Phát hiện gửi lại Track 1 (chưa đo tác động trên futures — KHÔNG kết luận thay)
- **T-1** `daily_atr_series` trả trung bình trượt kết thúc TẠI ngày D, mà `make_signal_fn`
  đọc nó lúc 14:00 cùng ngày D. Đo trên frame cổ phiếu: lệch trung vị 2,6-3,2%, tối đa 71%,
  7,7% trên các phiên biên độ rộng nhất.
- **T-2** `roska4_swing` khai báo `label_lag_days=0`; cả hai lần làm mới SPY (13:45 và 16:20)
  đều nằm sai phía so với slot 14:05. Ba trạng thái khả dĩ, cả ba đều là lệch live/backtest.
  CHƯA truy tới kết luận. Đo được: `spy_daily_live.csv` thiếu hẳn dòng 2026-08-25.
  Trên cổ phiếu, lag 0 làm kết quả XẤU đi (sản xuất lag 0: −$1.880 so với lag 1: +$20.018),
  nên đây không phải con số làm đẹp sổ — nhưng vẫn là chỗ hai luật có thể khác nhau.
- **T-3** `max_hold_days` đếm theo ngày LỊCH, nên số phiên nắm giữ thật đổi theo thứ trong tuần
  (vào thứ Hai → 5 phiên; vào thứ Tư → 3 phiên).

### Deliverables
scratch/stocks_stage0_backtest_from_track1_candidates_20260826.md (+ .json)
scratch/_stocks_stage0_ledger_{A,B,C,D}_causal_lag1_ema50.csv, _ledger_ext2018_prod.csv
scratch/_stocks_stage0_{probe,results,causality,sensitivity,stability,bootstrap}.json

### Next stage (STOCKS-1) — theo thứ tự
- [ ] Đóng băng dữ liệu: parquet bất biến per-symbol + sha256 vào hash cấu hình
- [ ] Chặn thiên lệch sống sót: dựng danh sách thành viên theo ngày, chạy lại
- [ ] Đo một mẫu khớp lệnh thật, đối chiếu trượt giá hoà vốn 7,38 bps/chiều
- KHÔNG làm: tinh chỉnh ema, suy lại ngưỡng biên độ, thêm sleeve Calm/Stress

---
## Sub-task: Track 1 Market View — dựng lại panel theo bản thiết kế (2026-08-28)
Status: DONE
Phạm vi tệp: `global_index/dash/realtime/**`, `global_index/dash/realtime-next/preview*.{html,js}`,
`monitor/backend/track1_market_view.py`, `monitor/test_realtime_dom.py`. Không đụng tuyến runner/engine.
KHÔNG commit — để chủ dự án tự xử lý.

### Đã đo trước khi dựng
- Đọc toàn bộ đường code: endpoint → `track1_market_view.build/regime` → `renderMarketView/renderRegime`.
- Dump payload thật: 3 sleeve, regime 3 trạng thái (KHÔNG phải 4), 2 feature (KHÔNG phải 9).
- **Phát hiện quyết định phạm vi:** quét cả 4 phiên đã lưu (25→28/08), mọi sleeve —
  **mọi luật chiến lược đều có `value: null`, `source: not_exposed_by_sleeve`; số dòng có giá trị = 0.**
  Ngưỡng thì CÓ công bố (`breadth_min 4`, `rr 1.5`, `max stop pct 0.02`…), còn giá trị thì không.
  → Bản thiết kế vẽ 4 lane sparkline một điểm mỗi slot; dữ liệu đó không tồn tại ở đâu cả
  (bản mock tự sinh bằng hàm ngẫu nhiên có seed). Vẽ theo sẽ là bịa số trên đúng trang mà
  người vận hành đọc số như số của chiến lược.

### Đã làm
- [x] Backend (bổ sung, đọc lại đúng tệp diagnostics đang đọc, không mở tệp mới): `_rule_lanes`
      → một hàng mỗi luật, một ô mỗi slot, 6 trạng thái ô; kèm `values_published` đếm được
      và `state_display` nói rõ LOẠI vắng mặt nào (gate chặn trước / detector không trả verdict /
      không có bản ghi / chưa chạy).
- [x] Frontend `/realtime`: verdict pill + chips, tab trong (Setup rules · Price context),
      thẻ lane, thẻ giá (OHLC + data health + nến + volume + slot + trục + chú giải),
      thẻ Setup (tóm tắt · nearest miss · conditions · trade levels), Regime Monitor
      (nhãn + số ngày giữ + 4 ô chỉ số + xác suất trạng thái + why-this-label + dải 60 ngày + chú thích).
- [x] CSS dùng token của `shared/tokens.css` — bảng màu bản thiết kế trùng token 1:1, không viết hex.
- [x] 6 trạng thái preview (Waiting/Live/Complete/Data delayed/Signal/Rejected) trong
      `preview-states.js`, đột biến payload THẬT theo đúng Luật 1 của tệp đó.
- [x] `preview.html` vốn thiếu hẳn hai section này → đã thêm, nếu không `?state=mv*` không vẽ vào đâu.

### Hai lỗi thật lộ ra khi dựng (đã sửa + có test)
- Slot bị gate từ chối đọc thành `NO SIGNAL` trong khi lý do ngay cạnh ghi "gate refused" —
  pill tự mâu thuẫn trong sáu chữ, và chỉ sai địa chỉ cho người vận hành.
- "no live bars since" trỏ vào slot cuối CÓ BẢN GHI thay vì slot cuối THẤY DỮ LIỆU —
  slot bị từ chối để lại bản ghi mà không có quan sát.

### Kiểm chứng
- 285 test xanh (`test_realtime_dom` 63 + `test_realtime_contract` + `test_dashboard_backend`).
- 8 test DOM mới + 2 test hồi quy; **đã đột biến từng cái để xác nhận đỏ được** (5/5 bắt đúng).
- Backend: self-check SC1–SC5 + đột biến 2 chiều (bơm giá trị → claim đổi theo; khai khống → đỏ).
- Chụp màn hình 1440 và 1024, cả 3 sleeve, hai tab: 0 lỗi console, không tràn ngang.

### Còn mở (KHÔNG phải việc của lượt này)
- Lane vẫn là chuỗi VERDICT, không phải chuỗi GIÁ TRỊ. Muốn đúng như bản vẽ thì phải sửa
  detector trả về số — tuyến engine/runner, không phải tuyến dashboard.
- Header trang tràn mép phải ở 1024px (`module-nav`, `header-live-context`). CÓ TRƯỚC,
  đã đo lại với panel rỗng để chắc chắn không phải do lượt này. Suite hiện chỉ đo 1440 và 390.

## Task: Stage 5ZZZ-R - restart liveness + post-fix shadow parity watch
Status: DONE (2026-08-29). **NO ORDERS.** orders_possible=False - blocker PAPER_SHADOW_EVIDENCE -
orders dir absent - approval unset - confirmation untouched (sha16 67504a1c8a31a6a4, dated 08-27) -
evidence gate NOT moved - no runtime trading file edited - no runtime evidence rewritten.

### THE PID IN THE 5ZZZ-Q REPORT WAS ALREADY STALE
Part A's first measurement disagreed with the record. 5ZZZ-Q closed with scheduler pid 3000; the
process table said **9356, started 08:59:41**. ops.log:
    2026-08-29T08:59:37 scheduler: scan_ok=True found=[3000] -> kill_then_start
**An ops.py restart ran from OUTSIDE this session.** So the Swing fix had been live since
**08:59:45**, not since anything this stage did. Not attributable to a person from the evidence,
so left unattributed.

### PART A - all conditions measured and met
mode track1-only-shadow · orders_possible False · **0 slot children** · next job of any kind
Sunday 18:30 ET (~31h) · legacy_entry_jobs 0 · books flat on all five counts.
My first scan claimed 5 running slot scripts - **it was my own command matching its own token
list**. Real answer 0. Caught by reading the output, not the count.

### PART B - restart done, and the brief corrected
    python monitor/ops.py restart --scheduler --track1-only-shadow --yes    exit 0
    scheduler 9356 -> 34564    backend 31248 -> 44480
Brief expected **backend pid unchanged**; it changed. Not a failure: `monitor/ops.py:1474`
defines restart as "replace scheduler, its run_live_day children, **and backend**". The external
08:59 run did the same. Read-only backend reconnected (broker=connected); no order path opened.

### PART C - fix is live, proven two ways
1. process: 34564 started 09:11:11 > last edit 08:25:46, and **0 runtime .py modified after**
2. behaviour: the fresh backend serves
   `.market_view.sleeves.roska4_swing.strategy.diagnostics.regime_basis = "previous session (lag 1)"`
   NKD agrees. **Exact JSON path located** - not a substring match on the whole payload.
Startup: `Track 1 SHADOW slots registered: 71 (no orders - the route's gate refuses)`.

### PART D - nothing has run on it yet (Saturday)
Monday 2026-08-31 IS a trading day (repo calendar; Labor Day 09-07 is not).
    global_nkd    Mon 01:10 ET = **Sun 23:10 machine** (night-slot trap)
    roska4_calm   Mon 09:32 decide / 10:02 observe
    roska4_stress Mon 10:35 (gate 10:30)
    **roska4_swing Mon 14:05 ET = Tue 01:05 VN - 50.7h out, THE slot this sequence exists for**

### PART E - parity: NOT_YET_OBSERVED x4
"newest live slot 2026-08-28T12:46:22, before the newest relevant fix 2026-08-29T08:21:23".
**No UNKNOWN turned into PASS.** Old evidence not rewritten. params_hash gap still caps a
post-fix slot at UNKNOWN.

### PART F - gate not moved
Fails `no_failing_days` (5 FAIL, 0 allowed) and `calm_decision_evidence`. **All five judgeable
days 08-24..08-28 are PRE-FIX**; window=5 days and allows zero failures, so it cannot be an
entirely post-fix window until 5 post-fix trading days run. Whether they pass: **not predicted**.

### TESTS - 13 new, **6 mutations / 6 caught / 0 survived**, 291 regression passed
One new test failed first run **for a real reason**: I guessed the confirmation record's path
AND a field. It lives at repo root and has **no order-approval field at all**. Test now asserts
that absence - a stronger claim.
**5 regression failures in test_track1_stage5m_d_..._20260823.py are NOT mine**: it pins 08-23
literals that legitimately changed 08-27 (3 SPY-ladder jobs added; operator signed the
retirement confirmation; lead blocker advanced B1 -> PAPER_SHADOW_EVIDENCE). None of the five
reads the process table. **Left failing, not re-pinned** - re-pinning asserts the new values are
correct, which is the operator's call.

### ⚠ FOR THE OPERATOR
A report that records a pid is describing something that moves - 5ZZZ-Q's was stale within the
hour. And **Monday 14:05 ET is the first post-fix Swing slot**: the first session where the
sleeve decides instead of refusing. Orders stay impossible, but the shadow evidence written from
Monday describes different behaviour from every day now in the qualifying window.

### OPEN
params_hash gap · SWING_TF_PARAM provenance unreproduced · no day-level bootstrap on any OOS ·
`track1-market-view` endpoint >300s and `track1-runtime` ~23s warm AND cold (not cold-cache);
**no pre-restart measurement exists, so I cannot say the restart changed it.**

### Files touched
scratch/test_track1_stage5zzzr_restart_liveness_postfix_parity_20260829.py,
scratch/track1_stage5zzzr_restart_liveness_postfix_parity_20260829.{md,json},
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md (appended)
**No runtime trading files. No gates. No thresholds. No params.**

## Task: Stage 5ZZZ-S - dashboard endpoint performance triage
Status: DONE (2026-08-29). **NO ORDERS.** orders_possible=False - blocker PAPER_SHADOW_EVIDENCE -
orders dir absent - approval unset - confirmation untouched (67504a1c8a31a6a4) - **scheduler
UNTOUCHED (pid 34564)** - no runtime trading file edited - no broker call from these endpoints.

### HALF THE PREMISE WAS MY OWN MEASUREMENT ERROR
5ZZZ-R reported ">300s and ~23s, on BOTH cold and warm, so not warmup". Re-measured on a quiet
machine: **market-view 1.20s, runtime 1.77s medians.** The two "warm" readings in 5ZZZ-R were
taken while an abandoned COLD market-view request was still running server-side - they measured
contention. **The "not just warmup" half was wrong and it was mine.**
What survived: `build()` **71.17s cold / 1.12s warm** in a fresh process - a 63x cliff, real.

### ROOT CAUSE
`_swing_cache` -> **11,410 `resample_5m` calls** = 85s of a 127s profiled cold build; keyed on
`id(df)` so a fresh process recomputes everything. It ran **INLINE on the request path and
blocked the whole payload** - every other sleeve waited behind a panel it does not depend on.
Also inline: calm_blocks 15.0s, label_regimes HMM fit 12.8s, stress daily_slices 9.7s.
**It was a DOCUMENTED deliberate trade** ("Pay once rather than show an empty panel"), so it was
changed deliberately with the reasoning recorded beside it, not silently reversed.
No subprocess, no shell, no ops.py, no PowerShell, no broker call anywhere in these paths.

### FIXED - all read-only dashboard code, ZERO runtime trading files
`monitor/backend/track1_market_view.py`: `_recon_cached` no longer computes inline on a cold
miss (spawns the worker the aged-out branch already used, **claims the key under the lock** so a
polled endpoint starts ONE worker not one per poll); `_recon_state` added so "still computing"
and "computed and it raised" stay different facts; calm phases and stress daily_slices deferred
the same way. **The stress mtime key is unchanged** - only WHEN it is computed moved, never WHAT
invalidates it (a TTL there was rejected upstream for a good reason).
`global_index/dash/realtime/realtime.js`: a muted "Rule values pending" chip - the frontend only
ever read `strat.rules`, so an empty list during warm-up looked **identical to a session with
nothing unmet**. Display only, decides nothing.

### BEFORE -> AFTER
    market-view warm   1.20s -> **0.01s**      (target <5s, met comfortably)
    market-view cold   >300s / 71.2s -> **21.9s**
    runtime     warm   1.77s -> **1.99s**      (target <2s, met but MARGINAL, range 1.36-3.74)
Nothing became unavailable when warm: payload compared key-by-key vs the pre-fix capture,
**0 keys lost, 0 added**, statuses identical, and Swing/NKD still show `previous session (lag 1)`.

### NOT FIXED, NAMED
`track1-runtime` 1.99s is dominated by the **order gate's AST wiring scan** - 160 `ast.parse`,
382,088 `ast.walk` per request, 1.85s, because `_gates()` runs `as_ledger()` AND
`may_enable_orders()` and each re-measures every blocker. It lives in `track1_gates.py`, a
**runtime trading file this stage may not edit**, and caching it dashboard-side would serve a
SAFETY display stale. **Correct fix needs authorisation: memoise `_identifiers` on
(path, mtime, size)** - a pure function of file content, so behaviour-preserving, and it speeds
up every gate consumer not just the dashboard.

### TESTS - 13 new, 6 mutations / 6 caught / 0 survived
**I introduced one real bug and an existing test caught it:** the stress branch ignored an
explicitly-named `now`, breaking 5 tests in the 5ZZZ-F UI-contract suite. Fixed - that suite is
**38/38**. This is the argument for those tests existing.
**5 remaining failures are PRE-EXISTING, and that was PROVEN not assumed** - the three in 5ZZZ-B
were re-run with the pre-stage inline behaviour restored at runtime and **fail there too**; the
two in 5ZZP are stale (5ZZQ deliberately added `label_regimes` with an mtime cache while the
5ZZP test forbids the name; 5ZZZ-B wired the two sleeves that the 5ZZP test still calls
"unwired"). **Left failing, not re-pinned** - same rule as 5ZZZ-R.
A `warm()` helper was added for tests/offline callers; the request path must never call it.

### Files touched
monitor/backend/track1_market_view.py, global_index/dash/realtime/realtime.js,
scratch/test_track1_stage5zzzs_dashboard_endpoint_performance_20260829.py,
scratch/test_track1_stage5zzz_b_strategy_diagnostics_20260828.py (precondition only),
scratch/track1_stage5zzzs_dashboard_endpoint_performance_20260829.{md,json}
**Backend restarted (allowed, to serve the fix). Scheduler NEVER touched.**

## Task: Stage 5ZZZ-T - gate identifier AST memoization
Status: DONE (2026-08-29). **NO ORDERS.** orders_possible=False - blocker PAPER_SHADOW_EVIDENCE -
orders dir absent - approval unset (and **proven unable to open orders even when set**) -
confirmation untouched (67504a1c8a31a6a4) - **scheduler pid 34564 NOT restarted** - zero broker /
subprocess / network calls.

### THE CHANGE - one pure function in a safety file
`track1_gates._identifiers`, memoised on **(str(Path(path).resolve()), st.st_mtime_ns,
st.st_size) -> frozenset**. Each key part earns its place: **mtime_ns** (NANOseconds - a coarse
clock lets two edits in one second look identical), **size** (the same-second, same-timestamp
rewrite mtime cannot see), path (no shared entries). Getting past both needs identical length AND
identical nanosecond stamp.
**stat() runs BEFORE the cache lookup** - a missing/unreadable file raises exactly as the read
used to and is NEVER answered from a remembered scan. "I cannot see the file" and "I saw the file
and it was clean" are the two answers this gate exists to keep apart.
**frozenset**, so one caller cannot edit what the next one measures.
**Only the parse is cached.** No decision, no blocker list, no measurement.

### BEFORE -> AFTER
    blocking()            0.212s -> **0.034s**   (6.2x)   ast.parse per call 40 -> **0**
    as_ledger()           0.448s -> 0.069s
    may_enable_orders()   0.212s -> 0.033s
    live_frame_wiring()   0.210s -> 0.023s
    **track1-runtime warm 1.89s -> 0.655s**  (target under 1s MET)
market-view warm unchanged at 0.031s. Cold calls are the 5ZZZ-S warm-up workers, not the gate.

### PROOF OUTPUT UNCHANGED - not a claim, a comparison
Full ledger (11 blockers, every measured_now + required_measurement_now) captured before the edit
and after -> **BYTE-IDENTICAL**. orders_possible False->False, blocking unchanged.

### PROOF OF INVALIDATION - adversarial on purpose
Each key part tested against the edit the OTHER cannot see:
  - **same-SIZE edit** (import alpha -> import bravo) - only mtime sees it
  - **same-MTIME edit** (content lengthened, timestamp forced back with os.utime to the exact ns)
    - only size sees it
  - a module gaining `from ib_insync import IB` must **stop reading clean** - it does
  - missing file raises + leaves NO cache entry; cached-then-deleted raises; bad syntax raises

### TESTS - 18 new, **7 mutations / 7 caught / 0 survived**
omit mtime - omit size - mutable set - unreadable=empty (the fail-OPEN one) - deleted file served
cached - blocker list in cache - memoisation removed. All red.
My test failed first run for a real reason: compared len() of a Python string while **Windows
writes CRLF**, so on-disk was 14 and the assert said 13. Now compares two on-disk sizes.
**Regression 362 passed / 7 failed - ALL SEVEN PRE-EXISTING, PROVEN:** every one re-run with an
**uncached _identifiers** (pre-stage logic byte for byte) and **fails there too** (4 standalone,
3 under a pytest plugin because they need fixtures). They pin a confirmation file that did not
exist when written (08-22 suite vs operator signing 08-27) and a slot count of 70 vs today's 71.
**Left failing, not re-pinned.**

### SCHEDULER STILL RUNS THE OLD CODE - stated, not hidden
pid 34564 was not restarted, so it holds the pre-memoisation module. It gets the speed-up whenever
it next starts. **Not a divergence risk**: the change is performance-only and the ledger is
byte-identical, so the two processes cannot disagree about whether orders are possible.

### Files touched
global_index/track1_gates.py (**the memoisation only**),
scratch/test_track1_stage5zzzt_gate_ast_memoization_20260829.py,
scratch/track1_stage5zzzt_gate_ast_memoization_20260829.md and .json
**Backend restarted once (to measure). Scheduler NEVER touched. No gate decisions, no blocker
logic, no strategy logic, no params.**

## Task: Stage 5ZZZ-U - Track 1 baseline archive and canonical index
Status: DONE (2026-08-29). **NO ORDERS.** orders_possible=False - blocker PAPER_SHADOW_EVIDENCE -
orders dir absent - approval unset - confirmation untouched - override grants nothing - **scheduler
AND backend both untouched** - zero broker calls - **0 files deleted / moved / renamed**, 0 old
reports rewritten, 0 runtime trading files touched.

### DELIVERABLE
**docs/futures/TRACK1_BASELINE_INDEX_2026-08-29.md** - the file to quote from.
558 files inventoried and classified; an index + manifest instead of editing history.

### I CHECKED THE BRIEF'S NUMBERS BEFORE PUBLISHING THEM
The brief hands over the figures. It is a hand-off, not a source, and this index is exactly the
document people quote without re-deriving. **All 36 headline numbers compared field by field
against the 5ZZZ-N artifact - all 36 match.**

### ONE LABEL DID NOT MATCH - cluster P&L vs marginal
The brief calls +18,429 / +3,906 / -464 the "Swing contribution". Those are the Swing **CLUSTER
P&L** (pnl_by_cluster.roska4_swing), an accounting split. What Swing **adds**, measured against
the no-Swing control already in the same artifact:
        window     cluster P&L   no-Swing    MARGINAL
        floor        +18,429      49,414     **+17,382**
        2025          +3,906      12,377      **+3,804**
        2026            -464       8,731        **-626**
Gap ~$1,000 on the floor - the other sleeves earn more when Swing is not competing for capacity.
**On 2026 the marginal figure is WORSE than the cluster one (-626 vs -464)** - and 2026 is the
window the operator's risk acceptance is most exposed to.
**The index publishes BOTH, labelled, side by side.** Self-check: the four cluster P&Ls sum
exactly to the full-stack net in all three windows.

### CLASSIFICATION (558 files)
    SUPPORTING_PROOF 381 · TEST_ARTIFACT 109 · REFERENCE_ONLY 24 · DECISION_RECORD 15 ·
    RESEARCH_ONLY 15 · REJECTED_RESEARCH 12 · CANONICAL 2
Named: 5ZZZ-H REFERENCE_ONLY (same-day column beside the D-1 one - easiest wrong column in the
repo) · 5ZZZ-I RESEARCH_ONLY (ema=10, not promoted) · 5ZZZ-L RESEARCH_ONLY + apparatus concern
**SUPERSEDED by 5ZZZ-M** · 5ZZZ-J/K REJECTED_RESEARCH (SPY/ES proxies) · 5ZZZ-M SUPPORTING_PROOF.
SUPERSEDED classes: pre-B1 blocker lists (B1 signed 08-27), stale slot-count docs (**71, not 70**),
old dashboard wording docs (5ZZZ-F, 5ZZZ-S).

### A GUARD ON MY OWN WORK
First pass curated 10 high-risk files by path - **4 of those paths did not exist**, filenames
written from memory. The curation was silently doing nothing for them. The script now **refuses to
run if any curated path is missing**; that is the only reason it surfaced before shipping.

### VALIDATION - 16 tests, **10 mutations / 10 caught / 0 survived**
Numbers checked **against the artifact, not pinned as literals**, so the index cannot drift.
Absences asserted too: never says same-day Swing is tradable, never claims orders possible.
Also checks **every file the index points at exists** - the failure the guard had just proven real.

### REMAINING BLOCKER BEFORE PAPER
**PAPER_SHADOW_EVIDENCE** - 5 judgeable days, 0 failures allowed, complete Calm decision evidence.
Every day now in the window predates the 5ZZZ-Q Swing fix, so it cannot be an entirely post-fix
window until 5 post-fix trading days run. First post-fix Swing slot: **Mon 2026-08-31 14:05 ET**.

### Files touched (all NEW)
docs/futures/TRACK1_BASELINE_INDEX_2026-08-29.md,
scratch/track1_stage5zzzu_baseline_archive_inventory_20260829.md and .json,
scratch/test_track1_stage5zzzu_baseline_index_20260829.py

## Task: Stage 5ZZZ-V - repo archive plan + Track 1 baseline history
Status: DONE (2026-08-29). **NO ORDERS.** orders_possible=False - blocker PAPER_SHADOW_EVIDENCE -
orders dir absent - approval unset - confirmation untouched - override grants nothing -
**scheduler AND backend untouched** - zero broker calls - **0 files moved / deleted / renamed** -
git reset/checkout NEVER used.

### THE BRIEF'S PREMISE DID NOT SURVIVE MEASUREMENT
Brief: ">1,000 TRACKED files from Track 1 stages, scratch reports, old baselines".
Measured with `git ls-files`: **829 tracked**, **3 tracked files in scratch/** (all stocks/TF
research, **0 Track 1**), **1,158 UNTRACKED**.
**Every Track 1 stage report, the canonical index, the pipeline doc and BOTH decision records are
UNTRACKED.** "Archive stale tracked artifacts" and "archive the Track 1 backlog" are two different
jobs; the brief assumed they were one.

### WHAT IS ACTUALLY TRACKED (829)
    ACTIVE_SOURCE 383 · UNKNOWN_KEEP 126 · ACTIVE_TEST 110 · already-archived 105 ·
    ACTIVE_DOC 40 · RUNTIME_EVIDENCE 16 · CANONICAL_DOC 3 · archive candidates 46
The 46 are old stocks/futures one-offs (check_*, diag_*, verify_*, measure_*) + stale .txt/.json.
**None is a Track 1 artifact.**

### A DETECTOR BUG CAUGHT BEFORE IT MOVED ANYTHING
First reference scan read .py/.md/.json/.js/.html but **NOT .css** -> all **18
global_index/dash/fonts/*.woff2** looked unreferenced. They are referenced, from
`global_index/dash/fonts/fonts.css`. **Shipping that pass would have archived the dashboard's
whole font set.** Caught by READING the candidate list, not trusting the count. Widened scan ->
candidates 63 -> 46.

### THE HARD-FAIL GUARD FIRED AND I DID NOT DISABLE IT
23 of 46 are top-level one-off .py, classified ACTIVE_SOURCE; the brief hard-fails on moving
source. The tempting fix was reclassifying root scripts so the guard would pass. **Asked instead.**

### OPERATOR DECISION (asked, not guessed)
1. **Archive nothing this stage** - plan + history only.
2. If archiving resumes: **the repo's own `_archive/{superseded,answered,dead,docs,scratch}` +
   docs/futures/ARCHIVE_LOG.md**, NOT the brief's new dated roots (avoids a 2nd convention).
The 46 candidates keep their recorded sha256_before, ready as the before-side of a later proof.

### A PRECEDENT FOUND BY ACCIDENT THAT ARGUES THE SAME WAY
pytest collection has **2 pre-existing errors**: `tests/test_raits_vs_hold.py` imports
`raits_vs_hold`, which now lives at `_archive/scratch/raits_scripts/raits_vs_hold.py`.
**An earlier archive move broke a test and it has stayed broken** - and ARCHIVE_LOG.md has **ZERO
mentions of it**, so unlike the futures moves it was never logged. Not caused by this stage (0
files moved, no deletions/renames). It is exactly the failure the guards exist to prevent.

### DELIVERED
**docs/futures/TRACK1_BASELINE_HISTORY_2026-08-29.md** - 13 sections, original baseline ->
runtime split -> B1/legacy retirement -> Calm two-phase -> dashboard diagnostics -> Swing same-day
problem -> D-1 reproduction -> retune/full grid -> SPY/ES rejection -> Stage M translation ->
operator override -> canonical numbers -> what remains. Publishes **BOTH** Swing figures
(cluster +18,429/+3,906/-464 and marginal **+17,382/+3,804/-626**).
scratch/track1_stage5zzzv_repo_archive_plan_20260829.json - all 829 classified, 46 deferred.

### VALIDATION - 16 tests, all pass
Since nothing moved, **"nothing moved" is itself checked**: every planned path still where the
plan says, every deferred hash unchanged, none of the brief's new roots exist, canonical links
resolve, no doc claims orders possible, same-day Swing still not live-tradable, Swing identity
still causal D-1 old/effective ema=50. `pytest --collect-only`: **4,402 collected**, 2 pre-existing errors.

### Files touched (all NEW, nothing moved)
docs/futures/TRACK1_BASELINE_HISTORY_2026-08-29.md,
scratch/track1_stage5zzzv_repo_archive_plan_20260829.json,
scratch/track1_stage5zzzv_repo_archive_and_history_20260829.md and .json,
scratch/test_track1_stage5zzzv_repo_archive_20260829.py

## Task: Stage 5ZZZ-W - untracked Track 1 artifact archive PLAN
Status: DONE (2026-08-29). **PLAN ONLY - 0 files moved.** orders_possible=False - blocker
PAPER_SHADOW_EVIDENCE - orders dir absent - approval unset - confirmation untouched - override
grants nothing - **scheduler AND backend untouched** - zero broker calls - git reset/checkout
NEVER used.

### ⚠ THE FINDING THAT OUTRANKS THE ARCHIVE: TRACK 1 IS NOT IN VERSION CONTROL
    global_index/track1_*.py     tracked: 0     untracked: 40
    git log --all -- "global_index/track1_*.py"   ->   EMPTY
**Never committed, on any branch.** Includes **track1_gates.py - the order gate itself** - plus
track1_live_source.py, run_live_day_track1.py, track1_normal_r4.py, monitor/backend/
track1_market_view.py, track1_runtime_reader.py, the 4 track1_b1/*.jsonl B1 evidence files, and
**track1_swing_paper_override.json**.
**NOT the same as the deliberate exclusions.** .gitignore:211 and :215 keep the confirmation
record and track1_runtime/ out of git WITH documented reasons ("the file that ARMS the route ...
must never be something a checkout can create"). The 40 source files are simply never added.
Told apart because `git ls-files --others --exclude-standard` already excludes ignored files;
confirmed per file with `git check-ignore`.
**Inconsistency named:** confirmation record = deliberately ignored + documented; swing override
beside it = neither ignored nor committed. Two decision records, two treatments.
**Cost, already paid:** 5ZZZ-T could not use git to attribute a regression and had to neutralise
its change at runtime, because `git show HEAD:<file>` answered "exists on disk, but not in HEAD".
**NOT FIXED HERE** - committing the live route is a decision, not a cleanup side-effect.

### INVENTORY
    untracked 1,220 | Track 1 635 | non-Track1 585
    MOVE_CANDIDATE 379 · KEEP 290 · IGNORE_NON_TRACK1 551
Move candidates: STAGE_REPORT 274, SUPPORTING_PROOF 74, RESEARCH_ONLY 13, REJECTED_RESEARCH 12,
GENERATED_TEMP 6. Kept: 112 tests, 82 UNKNOWN_KEEP, 43 uncommitted source, 5 stage reports,
6 proofs, 4 runtime/B1 evidence, 3 canonical docs, 1 decision record, 10 linked by canonical docs.

### TWO HAZARDS THE PLAN CAUGHT BEFORE ANY MOVE
1. **An active test imports a move candidate** (x2): test_track1_presleep_readiness_20260824 and
   test_track1_stage5m0_state_repair_20260823 import the very modules on the list. **This is
   exactly how tests/test_raits_vs_hold.py was broken by an earlier sweep and stayed broken.**
   Both -> KEEP; the classifier now protects ANY module an active test imports.
2. **Basename collision in a flat archive dir**: shadow_decisions_vault2026.jsonl and
   shadow_settlements_vault2026.jsonl each appear twice. A flat move would have had one
   **silently overwrite the other - data loss.** Archive paths now preserve relative dirs.
Neither was visible without doing the plan first.

### CONVENTION
`_archive/scratch/track1_2026-08-29/<original relative path>` - the repo's own, per ARCHIVE_LOG.md
and the 5ZZZ-V decision. No new root invented.

### VALIDATION - 16 tests, all pass, 0 gate failures
No canonical doc / decision record / runtime evidence / active test / source is a MOVE_CANDIDATE;
every candidate has a sha256 and a unique destination; no active test imports a candidate; no
destination exists yet; nothing moved. Two tests measure git LIVE so the plan cannot claim a
state that has since changed.

### IS AN APPLY STAGE SAFE? YES for the 379, with 3 conditions
1. re-verify sha256 immediately before AND after each move (scratch keeps changing)
2. an ARCHIVE_LOG.md entry per file incl. the "nothing imports it" check
3. re-run `pytest --collect-only` after; baseline **4,402 collected, 2 known pre-existing errors**
   - any NEW error means something on the list was still needed
**NOT safe inside a cleanup:** committing the 40 uncommitted source files - its own stage.

### Files touched (all NEW, nothing moved)
scratch/track1_stage5zzzw_untracked_archive_plan_20260829.md and .json,
scratch/test_track1_stage5zzzw_untracked_plan_20260829.py

## Task: Stage 5ZZZ-X - version the Track 1 route source
Status: DONE (2026-08-29). **COMMITTED 22f6086** - 163 files, 80,925 insertions.
**NO ORDERS.** orders_possible=False - blocker PAPER_SHADOW_EVIDENCE - orders dir absent -
approval unset - **confirmation NOT committed, still gitignored** - override committed but grants
nothing - scheduler AND backend untouched - zero broker calls - nothing moved/archived.

### THE FIX
Before: `global_index/track1_*.py` tracked **0**, untracked **40**; `git log --all` **EMPTY**.
The live route - including **track1_gates.py, the order gate** - had never been committed on any
branch. **Now it has a history.**
The cost was already being paid: 5ZZZ-T asked git whether 7 failures were its doing and got
"exists on disk, but not in HEAD", so it had to neutralise its own change at runtime instead.

### COMMITTED (163)
    source 46 · tests 113 · canonical docs 3 · decision record 1
46 source = the gate, live source, day runner, Normal-R4 detector, sleeves, slot table,
paper-readiness, replay-parity, b1/account-baseline audits + 2 monitor backend readers.
113 tests because committing the claim without its proof versions half of it.

### DELIBERATELY EXCLUDED
    track1_go_live_confirmation.json   gitignored :211 - **it ARMS the route**
    global_index/track1_runtime/**     gitignored :215 - append-only evidence
    global_index/track1_b1/*.jsonl     B1 account evidence, regenerated each session
    TASK.md / SCRATCHPAD.md            repo's own rule - operator working notes
    34 modified tracked files          **pre-existing operator WIP, modified BEFORE this
                                       session** - not mine, not reviewed. Committing them under
                                       "Track 1 route source" would misdescribe them
**The brief listed TASK.md; the repo rule forbids it. Raised the conflict instead of resolving it
myself - operator confirmed it stays out.**

### SPECIAL DECISION: SWING OVERRIDE **IS** TRACKED
Two decision records, opposite treatment, on purpose.
Confirmation stays out because it **ARMS** the route - a checkout must never create it.
That reasoning **does not transfer**: the override has grants_orders=false,
satisfies_shadow_evidence=false, parameter_promotion=false, evidence_promotion=false, **all proven
by tests in the same commit**. A checkout restoring it restores a SCOPE decision, never an ARMING
one. And it MUST be tracked: the route **reads it at runtime**, so paper scope would change
silently if lost, and the signed risk acceptance + 4 caveats exist nowhere else.

### PROOF NOTHING FORBIDDEN WAS COMMITTED (checked on the COMMIT, not the plan)
runtime evidence 0 · B1 evidence 0 · confirmation 0 · secrets/config_private 0 · TASK/SCRATCHPAD 0
config_private.py verified gitignored before staging; ADD list scanned for key/credential/private-
key patterns = **0 hits**.
Staged with an **explicit pathspec file - never `git add .`** - and the staged set compared to the
ADD list **as a SET** before committing: **exact match, 0 extra, 0 missing**.

### VALIDATION
93 tests passed across 6 Track 1 suites pre-staging · 0 broken canonical links · orders_possible
read from the **gate module, not the broker** · post-commit: gate still False, override still
grants nothing, orders dir absent, **34 pre-existing modified files still unstaged as they were**.

### WHAT THIS UNBLOCKS
5ZZZ-W's 379-candidate archive plan is now safer to apply: if an archive move ever breaks
something, **git can say what changed**. That was not true an hour ago.

### Files touched
scratch/track1_stage5zzzx_version_track1_source_20260829.md and .json
(plus the commit itself - no file contents were edited in this stage)

## Task: Stage 5ZZZ-Y - apply the untracked Track 1 archive plan
Status: DONE (2026-08-29). **341 archived · 38 restored · 0 deleted · 0 hash mismatches.**
**NO ORDERS.** orders_possible=False - blocker PAPER_SHADOW_EVIDENCE - orders dir absent -
approval unset - confirmation present & STILL GITIGNORED - override present & TRACKED, grants
nothing - scheduler AND backend untouched - zero broker calls - git reset/checkout NEVER used.

### ⚠ I BROKE 3 TESTS AND THE GATE CAUGHT IT
First sweep moved all 379 -> `pytest --collect-only` went from the baseline **2 errors to 5**.
**Root cause in my own tool:** the import scan took `m.split('.')[0]`, so
`from scratch.track1_foo import bar` was recorded as importing **`scratch`** - the real module
name thrown away. Every dotted submodule import was invisible.
Broken: scratch.track1_bootstrap_checkpoint_20260822 ·
scratch.track1_stage5c_shadow_readiness_probe_20260823 ·
scratch.track1_stage5zzzh_swing_d1_regen_20260829
**This is the SAME failure that left tests/test_raits_vs_hold.py broken by an unlogged archive
move - the one 5ZZZ-V found still broken and cited as the reason to be careful. It nearly
happened again in the stage that knew about it.** Only the brief's own gate caught it.
**Fix:** rescan every SEGMENT of every dotted import + every filename in a string literal ->
**38 moved files still referenced**, all restored, hashes **38/38**. Collection back to the
exact baseline: **4,418 collected, 2 pre-existing errors**.

### REVALIDATION BEFORE ANY MOVE
All 379 rechecked (the plan predates the 5ZZZ-X commit that changed 163 files' tracked state):
exists · sha256 matches · destination unique · destination absent · **not now tracked** · not
imported · not linked by canonical docs. **379 approved, 0 skipped.**
**Non-vacuity proved:** tracked set non-empty (992) + positive control (track1_gates.py present
in it), so the tracked-check could actually fire.

### MOVED -> `_archive/scratch/track1_2026-08-29/<relative path>`
STAGE_REPORT 244 · SUPPORTING_PROOF 66 · RESEARCH_ONLY 13 · REJECTED_RESEARCH 12 ·
GENERATED_TEMP 6 = **341** (4.3 MB). Relative paths preserved, which is what stops the two
`shadow_*_vault2026.jsonl` pairs overwriting each other. Each move verified the instant it
happened (old gone / new present / sha256 identical) with single-file rollback + abort.

### VALIDATION - all zero
missing 0 · hash mismatch 0 · old path present 0 · deletes 0 · tracked moved 0 · tests moved 0 ·
source moved 0 · runtime evidence moved 0 · decision records moved 0 · canonical docs moved 0 ·
broken links 0 · canonical-named paths missing 0 · restored intact 38/38.

### A GIT-STATUS READING THAT LOOKS ALARMING AND IS NOT
`git status --short` **collapses an untracked directory into ONE line**, so 342 archived files
show as a single `?? _archive/scratch/track1_2026-08-29/`. File level: **1,060 untracked, 342
under the archive dir, archive NOT gitignored.** Checked because a count dropping by a third
after a file-moving operation is exactly the shape of a mistake.

### ARCHIVE_LOG.md UPDATED
Repo's own format: destination, counts, source plan, manifest link, keep-policy, validation, and
an explicit note that **Track 1 source was committed first (22f6086)** - so if a move ever does
break something, git can now say what changed. The dotted-import lesson is recorded there too,
since the absence of exactly that note is why raits_vs_hold is still broken.

### Files touched
_archive/scratch/track1_2026-08-29/** (341 files + manifest),
docs/futures/ARCHIVE_LOG.md, docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md,
scratch/track1_stage5zzzy_apply_untracked_archive_20260829.md and .json

## Task: Stage 5ZZZ-Z - post-archive regression verification
Status: DONE (2026-08-29). **VERIFICATION ONLY - nothing changed, nothing moved.**
**NO ORDERS.** orders_possible=False - blocker PAPER_SHADOW_EVIDENCE - orders dir absent -
approval unset - confirmation present & STILL GITIGNORED - override present & TRACKED, grants
nothing - scheduler AND backend untouched - zero broker calls - git reset/checkout NEVER used.

### VERDICT: THE ARCHIVE IS SAFE. **NEW_FROM_ARCHIVE = 0.**

### RESULTS
    targeted (U/V/W)        42 passed,   6 failed  -> all STALE_TEST
    Track 1 core (11 suites) 270 passed, 1 failed  -> PRE_EXISTING
    collect-only            4,418 collected, 2 errors == **EXACTLY the baseline**
5ZZZ-X and 5ZZZ-Y have **no test suites** (a commit stage and a move stage). Gap NAMED, and their
guarantees verified directly instead: 341/341 archived files present, 0 hash mismatches, 38/38
restored intact, 0 deletes.

### THE 6 STALE_TEST FAILURES - each confirmed from its assertion, not assumed
    5ZZZ-V plan covers tracked      assert 829 == 992   (5ZZZ-X committed 163 after the plan)
    5ZZZ-W plan covers untracked    346 absent, all under the archive root
    5ZZZ-W no destination exists    the destinations exist - the apply stage created them
    5ZZZ-W planned paths exist      **341 gone = exactly what the manifest says was moved**
    5ZZZ-W no archive dir created   it exists
    5ZZZ-W finding matches git      its own message: "track1 source is now tracked - update the
                                    plan" - **it fired because the problem was FIXED by 5ZZZ-X.
                                    Working as designed; the failure is the signal.**

### THE 1 PRE_EXISTING - looked at closely because of its name
`test_19_orders_are_still_impossible_and_nothing_was_armed`.
**Its three order-safety assertions all PASS** (possible is False · blockers non-empty · orders
dir absent). It fails ONLY on `assert not Path('track1_go_live_confirmation.json').exists()` -
a suite written **2026-08-27** about a file the operator signed at **10:05 that same day**.
mtime 2026-08-27, sha16 unchanged all session -> **the archive cannot be the cause.**

### A FRAMING ERROR I CAUGHT IN MYSELF
Bare `pytest --collect-only -q` reports **1,004**, not 4,418 - a different SCOPE, not a
regression. The baseline was taken with an explicit path list. Comparing across two frames
manufactures an alarming number out of nothing. Re-measured with the same command: **exact match.**

### NOTHING RE-PINNED
All 7 still fail, each with its cause recorded - same rule as 5ZZZ-R/V/Y: editing a test until it
agrees is how a record stops being a record.

### Files touched
scratch/track1_stage5zzzz_post_archive_regression_20260829.md and .json,
docs/futures/TRACK1_RUNTIME_PIPELINE_2026-08-24.md

## Task: Stage 5ZZZ-AA - quarantine the runtime evidence I contaminated
Status: DONE (2026-08-30). **2 rows tainted · 0 deleted · 0 rewritten.**
**NO ORDERS.** orders_possible=False - blocker PAPER_SHADOW_EVIDENCE - orders dir absent -
approval unset - confirmation present & STILL GITIGNORED - override grants nothing - scheduler
AND backend untouched - zero broker calls - nothing moved/archived.

### THE ROWS
`global_index/track1_runtime/signals/track1_signals_20260829.jsonl` - 2 rows,
roska4_swing / TRACK1_SWING_1405 / 14:05 / shadow_live / reason overlap_disagreement.
Written **21:50:49 MT = 23:50 ET** by `pytest scratch -q` (Stage 5ZZZ-Z), which was **not
output-isolated**.
sha256 8e5f8c04... and 5729c4d2...

### FIVE INDEPENDENT PROOFS THEY WERE NEVER LIVE SLOTS
1. **2026-08-29 is a SATURDAY** - repo `is_trading_day()` = False
2. row claims **slot_time 14:05** but was written **23:50 ET**, nine hours later
3. **TRACK1_SWING_1405 = ZERO mentions** in scheduler_0829.log; **zero jobs fired** that day
4. payload price **M2K 103.0000 vs history 3048.3000** - a fixture value, not a quote
5. `data_source_identity` names the **ES** store while the sleeve is roska4_swing on **M2K**

### TAINT RECORD (append-only)
`global_index/track1_runtime/evidence_taint/evidence_taint_20260829.jsonl`
taint_id 5ZZZ-AA-20260830-001 · TEST_CONTAMINATION · action exclude_from_parity_and_shadow_evidence
**Matched by sha256 of the exact stored line, NOT a predicate** - a predicate could widen onto a
legitimate future row; a hash cannot.

### THE GAP I COULD NOT CLOSE - stated as a gap
3 data_observation files written in the same window (21:50:49, 22:17:10, 21:51:20). Their rows
carry their OWN historical dates, no fixture tell, duplicates 13/3/0. **No before-snapshot** ->
recorded as **touched_unproven, NOT tainted**. Tainting rows that might be real is the same
falsification in the other direction. **A measured "I could not tell", not a clean bill.**

### READERS UPDATED (read-side only)
NEW `global_index/track1_evidence_taint.py` - three states tainted/touched/clean (not two).
`track1_replay_parity`: newest_slot skips tainted rows; report surfaces them as
**TAINTED_TEST_EVIDENCE** - **never PASS, never FAIL** (scoring either way states something
about the route), and **surfaced not hidden** (an invisible exclusion looks like a row that
never existed).
    BEFORE roska4_swing = FAIL (a slot that never ran)
    AFTER  all four = NOT_YET_OBSERVED + 2 tainted rows listed
paper-readiness/audit: **verified unchanged, asserted by test** - 2026-08-29 never entered the
judgeable window, so no code change was needed. **Order gate untouched** - it does not import
the taint module, pinned by test.

### PAPER_SHADOW_EVIDENCE UNCHANGED
window 08-24..08-28 (08-29 absent) · same 2 failing checks · orders_possible False.
The contamination never reached the gate - **luck, not design**, which is why the guard exists.

### RECURRENCE PREVENTION
`track1_signals._refuse_production_write_under_pytest` fires only when **BOTH**: under pytest
AND destination inside `track1_runtime/`. Verified 4 ways: tmp_path allowed · scheduler allowed ·
production-under-pytest **refused** · deliberate opt-in via `TRACK1_ALLOW_RUNTIME_WRITE_IN_TEST=1`.
Narrow on purpose - a guard that blocks legitimate writes is one people learn to switch off.
`docs/futures/INVARIANTS.md` gained the incident + rule + guard.

### TESTS - 19 new, **6 mutations / 6 caught**, 139 regression passed
Mutations: empty taint record · newest_slot stops skipping · tainted scored PASS · guard removed ·
guard too wide (blocks tmp_path) · predicate widened to everything.
Tests pin BOTH halves: rows still on disk AND they count for nothing.

### Files touched
global_index/track1_evidence_taint.py (NEW), global_index/track1_replay_parity.py (read-side),
global_index/track1_signals.py (write guard),
global_index/track1_runtime/evidence_taint/evidence_taint_20260829.jsonl (NEW, append-only),
docs/futures/INVARIANTS.md, scratch/test_track1_stage5zzzaa_evidence_taint_20260830.py,
scratch/track1_stage5zzzaa_runtime_evidence_contamination_quarantine_20260830.md and .json

## Task: Stage 5ZZZ-AC - weekend SPY pre-NKD early warning job
Status: DONE (2026-08-30). **⚠ SCHEDULER NOT RESTARTED - the job is NOT live yet.**
**NO ORDERS.** orders_possible=False - blocker PAPER_SHADOW_EVIDENCE - orders dir absent -
approval unset - confirmation present & STILL GITIGNORED - override grants nothing - scheduler
AND backend untouched - zero broker calls - SPY csv NOT written by this stage - preflight_state
NOT written.

### THE JOB
    @sched.scheduled_job("cron", day_of_week="sun", hour=18, minute=0,
                         id="spy_weekend_pre_nkd_check",
                         name="SPY weekend pre-NKD check 18:00 ET (Sunday early warning)")
18:00 ET = half an hour BEFORE the existing Sunday 18:30 stop-repair sweep (the repo's own
weekend convention). One Sunday log in order: is the data there, then is the book protected.

### REQUIRED DAY IS ASKED FOR, NEVER COMPUTED
`_fresh.required_daily_close_through(_pd.Timestamp(_et_today()))` - the same function the 00:45
job and the freshness gate use.
    Sunday 2026-08-30      -> 2026-08-28 (the missing Friday)
    Sunday 2026-09-06      -> 2026-09-04 (**skips Labor Day Monday, NO special case in the job**)
    agrees with the 00:45 job on both
`_et_today()`, never `date.today()`.

### THE 55-HOUR GAP, AND A LIVE CHANGE TO IT
Friday 17:15 -> Monday 00:45 = 55h with nothing looking, ending 25 min before NKD 01:10.
**The immediate gap closed mid-stage:** spy_daily_live.csv read 2026-08-27 at 04:56 and
2026-08-28 after; mtime 05:11:31, rows 2426->2427.
**NOT the scheduler** (heartbeats only today, and it has no Sunday SPY job), **NOT
coverage_status** (read-only, checked in source), **NOT my tests** (harness monkeypatches the
launcher; all regression ran after 05:11). Most likely a manual run - **recorded as measured,
not guessed.** Tonight is fine either way; the STRUCTURAL gap is what this fixes.

### BEHAVIOUR
covered -> "nothing to do", **no provider call** · missing -> update_spy_csv --verify-strict
--require-through <day> --skip-if-covered · recovered -> WARNING naming the late Friday ladder ·
still missing -> ERROR naming required day / last day / 01:10 window / remaining 00:45 attempt /
manual command · provider fail -> **fail-closed** · dry-run -> invents no failure ·
**never writes preflight_state.json**.

### 00:45 JOB UNTOUCHED - pinned by test.

### MIRROR + JOURNAL
`SUNDAY_SPY_PRE_NKD_SLOT=(6,18,0)` mirrored like the Sunday sweep (unmirrored slot = fabricated
incident every week). Order verified 18:00 then 18:30.
`job_type: spy_weekend_pre_nkd_check` - a **THIRD** stream. Folding into the ladder would let a
Sunday success mark a **Friday** rung recovered - the exact fault 5ZZT fixed when a stop-repair
sweep closed failed refreshes.

### ops.py status
Weekend + short file -> names the Sunday job while still ahead AND always still names Monday
00:45. Weekday -> silent.

### TESTS - 27 new, 351 regression passed, 3 failed (ALL pre-existing)
**3 tests I updated because MY change made them wrong** (said plainly, not folded into a count):
SPY family four->five (count in the name grew, assertion NOT loosened to "at least four");
Sunday now has 2 slots and **the order is part of the assertion**; the first job after Friday
close is now this one.
**A test of mine that was wrong:** the "never writes preflight_state" check scanned raw source
and matched the **DOCSTRING**, which mentions preflight_state.json to say it does NOT write it.
Rewritten as an AST walk with docstring stripped; then string literals blanked too, because an
honest log line says "Friday" and a sentence is not a date calculation.

### ⚠ RESTART REQUIRED - NOT DONE
APScheduler reads cron ONLY at startup. Running scheduler pid 34564 (started 2026-08-29
09:11:11) predates this code and does not have the job.
    python monitor/ops.py restart --scheduler --track1-only-shadow --yes
Restart **before 18:00 ET today** -> job fires tonight (MT Sun 16:00 / VN Mon 05:00, ~10.8h out).
Otherwise the first automatic attempt is again Monday 00:45 - the very situation this removes.

### Files touched
global_index/run_scheduler.py (the job), monitor/backend/schedule_status.py (mirror),
monitor/backend/job_journal_reader.py (stream + text), monitor/ops.py (status line),
scratch/test_track1_stage5zzzac_weekend_spy_pre_nkd_20260830.py,
scratch/test_track1_stage5zzd_... + monitor/test_dashboard_backend.py (3 tests updated),
scratch/track1_stage5zzzac_weekend_spy_pre_nkd_check_20260830.md and .json

---
## Sub-task: Stage 5ZZZ-AF — realtime dashboard data visibility (2026-08-30, scope: global_index/dash/realtime/, monitor/test_dashboard_backend.py)
Status: DONE (frontend defect fixed + pinned); two backend findings reported, NOT patched

### Completed
- [x] Measured all 7 poll endpoints. Only /api/v1/track1-runtime is slow: 0.67-1.68s warm,
      7.09 / 9.04 / 9.37 / 11.06s on the first call after an idle gap (no cache; it walks the
      whole window_coverage + explanations tree). Every other endpoint <= 200ms.
- [x] Root cause 1 (FRONTEND_TIMEOUT_UX + BACKEND_COLD_CACHE): one flat AbortSignal.timeout(6000)
      for all seven fetches -> the slowest one aborts on the first load and the panel says
      "Track 1 runtime endpoint did not answer" about a backend that answered.
      Fix: per-endpoint timeout, 20000ms for track1-runtime + a one-in-flight guard.
- [x] Root cause 2 (first paint serialised): track1-runtime sat inside the awaited allSettled
      batch and render() ran only after it settled. Measured: Market View "--" and Regime empty
      from 0.5s to between 9.06s and 12.05s while market-view had answered in 41ms.
      Fix: track1-runtime polled on its own clock; batch renders without it.
- [x] Fourth panel state added: "reading" vs "did not answer" vs "not yet observed" vs running.
- [x] 4 regression tests added to monitor/test_dashboard_backend.py; 7 mutations all go red.
- [x] Focused suites green: test_dashboard_backend + test_realtime_contract + test_realtime_dom
      + test_realtime_skin = 299 passed in 258s.
- [x] Browser verified (hard reload, 3 poll cycles, 1600px and 1024px): no console/page errors,
      no horizontal overflow, all 11 panel hosts populated.

### Reported, NOT changed (needs a decision)
- Market View summary mixes two days: the "22/22 slots observed" count comes from the window
  ledger's LATEST day (2026-08-28) while the slot strip under it is TODAY's slots. The line
  already says "bars from 2026-08-28" for the chart but says nothing about the count.
- "Strategy levels unavailable" is printed for a sleeve whose own setup_boundary says
  entry_after_setup_only - i.e. the strategy never has standing levels. Reads as a fault.
- Today's 22 NKD slots are labelled "missed - no record was written for this slot" on a Sunday.

### Safety
orders_possible=false · blocking_now=["PAPER_SHADOW_EVIDENCE"] · no orders/ directory ·
scheduler, runner, broker, engine and gate files untouched · no commits made.

## Sub-task: Stage 5ZZZ-AG — neo Market View vào ngày giao dịch gần nhất (2026-08-30)
Status: DONE (chờ restart backend để có hiệu lực trên cổng 5002)

### Completed
- [x] `_anchor_day(today)`: hôm nay nếu là ngày giao dịch, ngược lại lùi về ngày giao dịch
      trước đó. Quyết định bằng LỊCH, không bao giờ bằng bằng chứng — để một ngày giao dịch
      không có dữ liệu vẫn neo vào chính nó và lỗ hổng lộ ra thay vì bị giấu.
- [x] `_coverage(root, day)`: phán quyết của window ledger cho ĐÚNG ngày đang hiện, thay vì
      lấy ngày mới nhất ledger có. Xoá lỗi "Complete 22/22 của thứ Sáu in trên 22 ô trống của
      Chủ nhật".
- [x] `now_hhmm = "23:59"` khi ngày neo không phải hôm nay — đồng hồ chỉ được phán xử slot của
      chính ngày nó thuộc về.
- [x] Payload công bố `today_et`, `session_is_today`, `session_anchor`, `session_anchor_reason`,
      `calendar_source`; chip đầu tiên trên trang: "Closed today — session 2026-08-28".
- [x] 4 test mới, 5 phép đột biến đều đỏ (kể cả biến thể "chỉ tránh thứ Bảy Chủ nhật, bỏ qua
      ngày lễ" và biến thể "cho _anchor_day nhìn thấy bằng chứng").

### Đo được sau khi neo (Chủ nhật 2026-08-30, dựng server kiểm trên cổng 5099)
- NKD: 22 slot từ "missed/no record" → "no_signal", coverage complete 22/22, bars 2026-08-28.
- Rule lanes từ "NO RULE EVIDENCE" → 8 làn thật; gate allow 22/22 pass, freshness allow 22/22 pass.
- Lý do không có tín hiệu hiện ra: "regime 'Calm'; this sleeve trades ['Normal']".
- Data health từ "Provider not recorded" → "Latest 15:54 ET".

### Lộ ra sau khi neo — CẦN XEM
- roska4_swing phiên 2026-08-28: chỉ 9/23 slot có bản ghi, 14 slot no_record, ledger nói
  `unobserved`. Lỗ phủ thật của thứ Sáu, trước đây bị che vì trang đang xem hôm nay.
- NKD: 5/8 quy tắc (ema10 filter, regime lag 1, japan session window, fixed stop 2x daily atr,
  max hold context) `not_published` trên cả 22 slot — bộ dò không ghi giá trị ra bằng chứng.
- Stress: 11/13 làn `not_published` trên cả 24 slot.

### Còn nguyên, chưa sửa
- Dải ngữ cảnh trên đầu trang (`sessionDate`) vẫn neo theo snapshot cuối của runner LEGACY,
  ngày 2026-08-24 — sáu ngày trước, và khác hẳn ngày Track 1 thật sự chạy.
- `metricEquity` "not measured": bản ghi baseline tài khoản mới nhất 2026-08-29 13:29 UTC,
  ngưỡng 24h, hiện 24,7h → `baseline_record_stale`. Chạy tay
  `python -m global_index.account_baseline_audit` là đầy lại. Không có job tự động cho việc này.

## Sub-task: Stage 5ZZZ-AH — bằng chứng ghi thật thắng bản phát lại + ngày đầu trang (2026-08-30)
Status: A và B DONE. D CHẶN — cần quyết định vì nó chạm engine dùng chung.

### Completed
- [x] A. Thẻ điều kiện hỏi kho ghi thật trước (`track1_strategy_diagnostics.recorded_for`,
      hàm đã có sẵn, trước đó chỉ test gọi). Không có bản ghi mới phát lại. Tách 10 dòng
      gán khối thành `_apply_r4_block` dùng chung cho cả hai đường — không viết lại logic.
- [x] B. Ngày đầu trang lấy ngày phiên Track 1, legacy làm dự phòng. Đo trên trình duyệt:
      "Aug 24, 2026" → "Aug 28, 2026". Lời gọi nhật ký phiên legacy GIỮ NGUYÊN ngày legacy,
      và có test ghim để không ai "dọn cho gọn".
- [x] 3 test mới, 4 phép đột biến đều đỏ (bỏ nhánh đọc bản ghi / mất dự phòng /
      header quay về legacy / đổi luôn lời gọi log legacy).
- [x] Kiểm trên dữ liệu thật: cả ba rổ rơi về `reconstructed_today` đúng như thiết kế,
      vì chưa ngày nào có bản ghi thật.

### D — vì sao chặn (đọc code, không đoán)
Hai bộ từ vựng không khớp nhau:
- Bộ dò công bố CỔNG của chính nó: session_bars, regime, daily_atr, bars_so_far, setup_bar.
- Kênh tín hiệu khai TÊN QUY TẮC: ema10_filter, regime_lag_1, japan_session_window,
  fixed_stop_2x_daily_atr, max_hold_context, admission_cap_result.
Chỉ `regime` ↔ `regime_lag_1` khớp thẳng.

Ba quy tắc do CHÍNH lớp bọc của rổ quyết bằng `if` tường minh (nối được, không suy diễn):
  cổng SPY short → spy_d1_close_below_sma50_short_filter
  bộ lọc ngữ cảnh → r4_prior_range_filter
  neo lại stop theo ATR ngày → fixed_stop_2x_daily_atr

Hai quy tắc nằm TRONG `TrendFollowStrategy.generate_signal` — lớp engine dùng chung với
backtest: ema10_filter / ema50_filter, entry_bar_volume_filter. Đụng vào là đụng engine.

Hai "quy tắc" không phải điều kiện vào lệnh nên sẽ mãi mãi không có verdict:
  japan_session_window — cửa sổ áp bằng cắt lát bar trước khi bộ dò chạy
  max_hold_context — tham số THOÁT lệnh, không phải điều kiện vào

### Files touched
monitor/backend/track1_market_view.py, global_index/dash/realtime/realtime.js,
monitor/test_dashboard_backend.py

## Sub-task: Stage 5ZZZ-AJ — panel phải khớp luật engine (2026-08-30)
Status: Sửa 1 và mục 3 DONE. Sửa 2 (engine) CHƯA ĐỤNG — chờ duyệt kế hoạch.

### Đo được (con số làm cơ sở cho mọi việc dưới đây)
- Dòng "Price vs EMA" in verdict cho một phép kiểm nó không thực hiện. Đối chiếu trên kho
  thật, 3.999 bar mỗi rổ, giữa câu trả lời của dòng đó và cổng EMA thật của engine:
     NKD   trùng 52,7% · dòng BÁO ĐẠT khi engine CHẶN 1,9% · dòng BÁO TRƯỢT khi engine CHO 45,4%
     Swing trùng 53,8% · 3,1% · 43,1%
  Bar tệ nhất: dòng báo "đạt" khi cách EMA 7,06%, ngưỡng engine là 0,50% — gấp 14 lần.
  Luật thật: |giá đóng bar KÉO LÙI − EMA| / EMA <= 0,005 (phép kiểm KHOẢNG CÁCH, bar[-2]).
  Dòng đang in: giá đóng bar TIẾP DIỄN − EMA > 0 (phép kiểm DẤU, bar[-1]) — đó là cổng HƯỚNG.
- Toàn bộ bằng chứng đã lưu: 291 bản ghi slot, 5 ngày, 3 rổ, 24 luật khai báo.
  Số luật từng có verdict: 0. Không một cái nào.

### Completed
- [x] Sửa 1: bỏ verdict khỏi dòng EMA, đổi tên thành "Close minus EMA", giữ nguyên con số.
      Không tính lại luật thật ở đây — làm vậy là bản cài đặt thứ hai của một luật đang giao dịch.
- [x] Mục 3: ba tên không phải điều kiện vào lệnh (japan_session_window, max_hold_context,
      stop_arm_rule) khai trong NOT_ENTRY_CONDITIONS ngay dưới bảng RULES — không chép sang
      dashboard. Chúng VẪN nằm trên bản ghi bằng chứng; chỉ đổi cách panel trình bày.
      Panel: NKD "6 of 8 rules publish no verdict" -> "4 of 6", cộng một hàng cấu hình.
- [x] 3 test mới, 6 phép đột biến đều đỏ (kể cả "quét nhầm luật vào lệnh" và "tên bị đổi,
      trôi khỏi RULES").
- [x] Kiểm trình duyệt 1026px và rộng: không tràn ngang, hàng cấu hình 60px, hai mục có tooltip.
      Thẻ điều kiện hiện "Close minus EMA −376,71 · NOT REPORTED".

### Files touched
global_index/track1_strategy_diagnostics.py, global_index/track1_signals.py,
monitor/backend/track1_market_view.py, global_index/dash/realtime/realtime.js,
global_index/dash/realtime/realtime.css, monitor/test_dashboard_backend.py

## Sub-task: Stage 5ZZZ-AK/AL/AM — engine báo cáo cổng, lưới theo cây nến (2026-08-30)
Status: DONE về code và cổng. Còn 1 test đỏ đang truy nguyên nhân (thứ tự chạy).

### Đo được — nền của mọi quyết định dưới đây
- Verdict của một cây nến là BẤT BIẾN. Cắt cửa sổ ở từng mốc 5 phút qua một phiên thật:
  865 verdict được tính, 80 cái khác nhau, KHÔNG một cái nào đổi giữa các lần cắt.
  => đơn vị đúng là CÂY NẾN, không phải slot.
- Trong MỘT slot, luật khối lượng được trả lời 22 lần: 12 đạt, 10 trượt. Ô "một luật một
  slot" chưa bao giờ có giá trị — đó là lý do 22/24 luật ghi "không công bố" suốt 291 bản ghi,
  chứ không phải vì thiếu dữ liệu. Đúng 2 luật từng điền được ô là đúng 2 luật quyết một lần
  mỗi slot (gate_allow, freshness_allow).
- Tương đương engine: 516 bar, 516 giống hệt, 0 lệch, kể cả khi hàm nghe ném lỗi.
- Phễu tự khớp số học 22 -> 22 -> 22 -> 12 -> 2 (mỗi tầng `tới` = `đạt` của tầng trên).

### Completed
- [x] engine `generate_signal` + `check_volume_pattern` nhận hàm nghe tuỳ chọn, báo 4 cổng
      tại đúng chỗ quyết định. Không truyền thì tốn một phép `is not None` mỗi cổng.
- [x] lớp bọc của rổ báo 3 cổng; CHỈ đường live truyền bộ quan sát, đường backtest không —
      nên backtest bất biến theo cấu tạo, không phải nhờ kiểm.
- [x] kênh `bar_gates` RIÊNG, không đổ vào `gates` cấp slot — nếu đổ chung thì "điều kiện
      trượt gần nhất" sẽ đổi từ `setup_bar` (nói về cả phiên) thành một cây nến đơn lẻ, và
      `volume_resume_surge` trượt 388/397 nên gần như mọi slot đều bị đổi câu trả lời.
- [x] lưới `bar_gate_grid`: một chuỗi ký tự mỗi luật, P/F/-, cộng đếm đạt/tới. Lưu bằng
      chuỗi nên 22 nến tốn 22 ký tự; khối 3.737 -> 4.371 byte.
- [x] dashboard vẽ lưới, tách hẳn khỏi làn theo slot, có nhãn "one cell per bar, not per slot".
- [x] 12 test mới tổng cộng; 7 phép đột biến cho riêng lưới đều đỏ, gồm "vẽ chưa-chạy-tới
      thành đạt" và "thành trượt".

### Cổng — không đổi
- Đối chiếu 1.223 dòng cả ba cửa sổ: pass, cả trước và sau cả hai chặng.
- Định danh đối tượng: pass.
- Cổng chặn lệnh: băm f715adaac6e21bcb... GIỐNG HỆT trước và sau.
- Artifact cam kết: ba băm nguyên vẹn suốt phiên làm việc.

### Hai lỗi đỏ KHÔNG phải của tôi
- `test_rejects_negative_sector_strength`: `run_scanner` giống hệt bản HEAD, mọi sửa của tôi
  nằm từ dòng 293 trở đi.
- 3 test nhóm `test_c_*` trong tệp cổng: đỏ vì `track1_go_live_confirmation.json` do chủ dự án
  ký ngày 27/08, còn test viết ngày 23/08.

### Hai lần tôi tự bắt lỗi của chính mình
- Viết `not (a <= b)` thay cho `a > b` ở cổng EMA — không tương đương khi NaN, và cổng 1.223
  dòng KHÔNG bắt được vì ba cửa sổ có thể không chứa NaN nào. Đã có test riêng ghim ca đó.
- Đo "0 nến cho cả 22 slot" rồi suýt báo một lỗi live nghiêm trọng — hoá ra tôi đọc parquet
  thô (không múi giờ) trong khi đường live dùng khung ĐÃ gắn múi Tokyo. Đo nhầm khung.

### Stage 5ZZZ-AN — cuộc đua vẽ trang do chính chặng AF gây ra
- [x] Tìm ra và sửa: `pollTrack1` vẽ trang trước khi lô về, làm mọi ô số đọc "--" một nhoáng.
      Ba lượt chạy cùng tổ hợp: 2 đỏ / 4 đỏ / 1 đỏ (cái cuối là lỗi scanner có sẵn).
- [x] Cờ do LÔ bật, ngay trước lượt vẽ của lô. 3 phép đột biến đều đỏ.

### Chốt cuối phiên
- Test: 345 passed, 1 failed (scanner có sẵn, `run_scanner` giống hệt bản HEAD).
- Cổng chặn lệnh: băm f715adaac6e21bcbe226b3bd71e6a8d1 — GIỐNG HỆT mốc đầu phiên.
- Artifact cam kết 1.223 dòng: ba băm nguyên vẹn.
- Không có thư mục orders/. Scheduler không bị chạm.
- 10 tệp đã sửa; không commit gì.

## Sub-task: Stage 5ZZZ-AO — bảng khai luật khớp với engine, CHẶNG 1/3 (2026-08-30)
Status: DONE. Chặng 2 (Stress) và 3 (Calm) nằm trong test dưới dạng xfail nghiêm ngặt.

### Đo được — bốn rổ, ba cơ chế
- NKD + Swing dùng chung `track1_normal_r4` -> `TrendFollowStrategy`. Đã có seam báo cáo.
- Stress dùng `track1_stress_mnq`, báo qua `basket_state` (cơ chế riêng, đã có giá trị).
- Calm dùng `track1_calm_a`: KHÔNG có tham số observer, KHÔNG phát sự kiện nào.
  Sáu điều kiện vào lệnh của Calm chưa từng có verdict ở bất cứ đâu.

### Lệch tìm được
- NKD chạy cổng khối lượng (2 nửa) + cổng SPY short, KHAI CẢ HAI ĐỀU KHÔNG.
  Cổng khối lượng giết 20/22 nến -> luật bị bỏ sót chính là luật quyết định.
- Swing chạy cổng chế độ (cùng hằng số, cùng lag_days=1 như NKD), KHÔNG khai.
- Stress phát `wide_count` mà không khai; `below_count` <-> `breadth_down_count` lệch tên.

### Completed
- [x] Bảng khai: Swing +regime_lag_1; NKD +entry_bar_volume_filter +spy_d1_close_below_...
      Không đổi tên nào — NKD mượn đúng tên Swing đã khai. Test cũ dùng phép BAO HÀM nên
      thêm tên không làm nó đỏ.
- [x] `EMITTED_TO_DECLARED` + `EMITTED_TO_DECLARED_BY_SLEEVE` + `declared_for()` một chỗ,
      ngay dưới RULES. `ema_proximity` là mục duy nhất phụ thuộc rổ (ema10 vs ema50).
- [x] Test chống lệch CHẠY BỘ DÒ THẬT, đối chiếu hai chiều, cho cả bốn rổ.
      5 phép đột biến đỏ, gồm hai cái đúng bằng trạng thái trước khi sửa.
- [x] Test đó bắt ngay một lỗi CỦA TÔI: NKD chạy `apply_context_filter=False` nhưng đoạn
      phát cổng vẫn báo `r4_context_filter: đạt` — công bố một cổng chưa từng áp dụng là
      đã đạt. Đã sửa: chỉ báo khi rổ thật sự có bộ lọc.

### Cổng — không đổi
- Đối chiếu 1.223 dòng cả ba cửa sổ: pass. Định danh đối tượng: pass.
- Băm cổng chặn lệnh f715adaac6e21bcbe226b3bd71e6a8d1 — giống hệt mốc đầu phiên.

### 8 test đỏ, KHÔNG cái nào của tôi (đã phân loại từng cái)
- 6 cái: guard `_refuse_production_write_under_pytest` CÓ Ở HEAD, test stage cũ viết trước nó.
- 1 cái: `JSON.stringify` trong `mvChartSvg` — code biểu đồ của phiên khác, không có ở HEAD.
- 1 cái: scanner `sector_strength`, đã chứng minh từ trước.

### Files (sạch, không lẫn phiên khác)
global_index/track1_signals.py, global_index/track1_normal_r4.py,
scratch/test_track1_stage5zzz_ao_rule_vocabulary_20260830.py (mới)

## Sub-task: Stage 5ZZZ-AQ — bộ dò Calm báo cáo cổng, CHẶNG 3/3 (2026-08-30)
Status: Bộ dò XONG và chứng minh trơ. Phần tới panel CHƯA — cần đổi hình dạng bản ghi.

### Chứng minh baseline không đổi — chặt hơn cổng
Cổng đối chiếu chỉ so 6 cột (day, exit_day, direction, entry, exit, pnl) trong khi CalmSetup
có 13 trường. Nên tự dựng phép so riêng: băm SHA-256 toàn bộ 13 trường của từng lệnh,
MES và MNQ x ba cửa sổ, TRƯỚC khi sửa.
    floor/MES 164  b2364e4d41efc84c   vault2025/MES 169  3e6e0bd33b6b2abf
    floor/MNQ 185  11a234505759dc3d   vault2025/MNQ 180  4854411259764410
    vault2026/MES 181  2d4d5dcc62d2ccce   vault2026/MNQ 190  744ec1a9a38900d7
    TỔNG 1.069 lệnh
SAU khi sửa: sáu băm GIỐNG HỆT. Không một trường nào đổi.

### Cổng
- Phá thử TRƯỚC khi sửa: dời close_loc_max 1/3 -> 1/2 làm cổng ĐỎ (thừa lệnh 2026-01-05),
  khôi phục thì XANH lại. Cổng gác thật.
- 13 test_b_ sau khi sửa: 13 passed / 13 phút 44 (mốc trước 12 phút 46).
- Băm cổng chặn lệnh f715adaac6e21bcbe226b3bd71e6a8d1 — giống hệt mốc đầu phiên.

### Completed
- [x] Ba điểm phát trong bộ dò: entry_conditions (3 luật giá), detect_setup_before_entry
      (chế độ Calm D1), detect_entry_for_day (giờ vào lệnh). Tham số tuỳ chọn, mặc định rỗng.
      `detect` — đường backtest — KHÔNG mọc thêm tham số nào.
- [x] Ba nhánh kiểm dữ liệu (biên độ <= 0, giá mở = 0, giá đóng = 0) KHÔNG báo như luật.
- [x] Tên phát ra CHÍNH LÀ tên đã khai — Calm chỉ có một nguồn quyết định nên không cần cầu nối.
- [x] Bản phát lại của dashboard thu cổng và nói được vì sao không set up.
- [x] 3 test mới + 4 phép đột biến đều đỏ, gồm "báo nhánh kiểm dữ liệu như luật" và
      "pha quyết định rò cổng của pha quan sát".

### CHƯA XONG — và lớn hơn một dòng nối
`calm_blocks` ưu tiên BẢN GHI THẬT, chỉ phát lại khi không có bản ghi. Ngày 28/08 có bản ghi,
nên phần vừa nối không được dùng. Để cổng Calm hiện trên ngày CÓ bản ghi thì slot live phải
thu và GHI chúng vào bản ghi shadow-intent — tức đổi hình dạng một tệp bằng chứng đang chạy,
tuyến runner. Cần kế hoạch riêng trước khi chạm.
Điểm phát thứ tư (`stop_risk_computed`, ở tầng gọi live) nằm cùng gói đó.

### Files
global_index/track1_calm_a.py, global_index/track1_strategy_diagnostics.py,
scratch/test_track1_stage5zzz_ao_rule_vocabulary_20260830.py

## Sub-task: Stage 5ZZZ-AS — mảng hiển thị (2026-08-31)
Status: DONE về code và test. Chưa restart backend 5002.

### Completed
- [x] Luật theo nến rời bảng làn. Phân loại SUY RA từ kênh phát (`SLOT_LEVEL_GATES` /
      `PER_BAR_GATES` đặt cạnh bảng khai), không phải danh sách viết tay.
      Đo trên payload thật 2026-08-28: NKD 6 làn -> 4, Swing -> 3, Stress giữ nguyên 13.
      Stress và Calm không mất gì THEO CẤU TẠO — bộ dò của chúng không có kênh theo nến.
- [x] Lưới thành tab thứ ba (`Setup rules · Detector rules · Price context`). Luôn hiện,
      kể cả khi 0 nến; trạng thái rỗng lấy lý do từ chính cổng đã trượt.
- [x] Thẻ Calm vẽ `gates`. Kiểm trên trình duyệt: 4 cổng, có ngưỡng và giá trị.
- [x] 3 test cũ của tôi đỏ vì ghim thiết kế cũ — cập nhật có chủ đích, giữ ý bảo vệ,
      cộng assertion ngược (`ema10_filter` PHẢI KHÔNG còn ở làn).
- [x] Tràn ở 390px do tab thứ ba đẩy chú thích ra ngoài — cho xuống dòng, 3 bề rộng pass.
- [x] Dải tab từng biến mất khi không có làn, kéo theo lối vào tab lưới. Gặp lúc 04:25 ET
      thứ Hai: phiên neo vào hôm nay, hôm nay chưa có bản ghi. Đã sửa + ghim test.

### Kiểm trên trình duyệt thật
88 ô = 4 hàng x 22 nến; đếm màu 58/20/10 khớp từng ký tự. Biểu đồ ẩn ở hai tab chi tiết,
hiện ở Price context. Không tràn ở 487px và 390x844 (test DOM).

### Cổng
327 passed / 0 failed. Băm cổng chặn lệnh f715adaac6e21bcbe226b3bd71e6a8d1 — giống hệt đầu phiên.

### Còn lại
- `regime_lag_1` vẫn trống cho tới khi route ghi cổng vào TỪNG bản ghi slot (tuyến runner).
- Dữ liệu Calm chỉ có từ phiên live kế tiếp.
- CHƯA COMMIT: realtime.js, realtime.css, monitor/test_dashboard_backend.py — lẫn việc phiên khác.
- CẦN khởi động lại backend cổng 5002 + Ctrl+F5.

---
## Sub-task: Dải nhóm 01/02/03 cho /realtime (2026-09-01)
Status: DONE — chưa commit

### Phạm vi
global_index/dash/realtime-next/next.js, next.css (chỉ 2 file này)

### Đã làm
- [x] Thêm ba dải nhóm Operations / Book / Market vào cột workspace của /realtime,
      theo bản design "Realtime Dashboard.dc.html"
- [x] Sắp lại tám mục cho khớp dải đặt tên chúng

### Đo được
- Trang live đã có SẴN mọi block của design (kể cả Track 1 Market View và
  Calm · two phases) và đã trùng bảng màu (#08090c/#e8ebf0), thang chữ 17px/600,
  font số IBM Plex Mono, rail hai cột. Delta thật chỉ là cách nhóm.
- .primary-column là flex column và bảng nền gán order tường minh
  (Open Issues -2, Open Positions -1, Decision 1, Orders 2). Dời node KHÔNG đủ:
  đo ra Open Orders nằm cách tiêu đề của nó 3400px. Phải gán order inline.
- Test: 10 passed (skin) + 89 passed (dom + contract).

### Còn mở — cần chủ dự án quyết
- Việc nhóm ĐÈ một luật có chủ đích: bảng nền cố ý đẩy Open Issues và
  Open Positions lên đầu cột. Design lại nhóm chúng xuống. Hai cái không cùng đúng.
- Now Monitor và hàng chỉ số KHÔNG bị kéo vào dải, vì restructure() cố ý nâng
  chúng lên .overview-header để Now Monitor và journal cùng bắt đầu một dòng.
- Không test nào bắt được lỗi thứ tự nói trên — nó xanh cả khi dải đặt sai chỗ.

### Cập nhật (2026-09-01, cùng sub-task): làm đầy đủ theo design
- [x] Kéo Now Monitor vào 01 Operations và hàng chỉ số (#metrics) vào 02 Book,
      đúng như design. Hai chỗ chệch nêu ở mục trên đã bỏ.
- [x] Bỏ placeNowMonitor() (nó nâng Now Monitor lên .overview-header, giành node
      với việc nhóm). Thay bằng foldEmptyHeader(): header rỗng thì ẩn, KHÔNG xoá.
- Số mục mỗi dải giờ khớp design: 01 = 4 · 02 = 3 · 03 = 3.
- Đo được, không đoán:
  * Lookup phải quét toàn document, không quét trong cột — Now Monitor và #metrics
    khởi đầu nằm ở .overview-header, quét trong cột sẽ âm thầm dựng dải 3 mục.
  * groupBands phải chạy SAU renderWindowBar, nếu không #nextWindowBar bị tạo vào
    cái header vừa ẩn = thêm vào trang mà không hiện ở đâu.
  * .window-bar display:none là CÓ CHỦ ĐÍCH (skin-e.css:438 — design bỏ thanh này
    vì Now Monitor đã có sẵn đếm ngược). KHÔNG phải hồi quy do việc dời gây ra.
- Test sau thay đổi: 99 passed (skin + dom + contract). Không lỗi console.
- next.css:170 `.overview-header > .now-monitor { order: -1 }` nay thành vô hiệu;
  để nguyên vì gỡ thêm rủi ro, cần thì dọn sau.

### Cập nhật 2 (2026-09-01): bốn chỗ lệch thị giác so với design
Chủ dự án hỏi "sao ko giống file html" — đúng. Tôi đã NÓI QUÁ ở lượt trước:
kết luận "đã hiện thực gần hết ngôn ngữ thị giác" chỉ dựa trên 6 token trùng
(nền, màu chữ, cỡ tiêu đề, font số, rail 2 cột). Sáu token không đủ để nói vậy.

Đo lại và đã sửa 4 chỗ:
- [x] Ô Now Monitor: chuyển vạch accent từ cạnh TRÊN sang cạnh TRÁI, giữ nguyên
      4 biến màu của skin. Đo ra 4 màu khớp design: 5b9cf0 / 9d8cf5 / 3a6ea8 / 6b5cb8
- [x] Model Inputs: dời VÀO TRONG Regime Monitor (design đặt nó là dải đầu của
      panel đó), thay vì là thẻ cấp cao cạnh Paper Equity
- [x] Hàng chỉ số: gộp 2 hàng thành MỘT hàng 4 thẻ 1.25fr/1fr/1fr/1fr;
      .metrics-figures rỗng thì ẩn, không xoá
- [x] Đệm mục: 24px 26px -> 18px 22px
- Đè từ next.css bằng specificity cao hơn, KHÔNG sửa skin-e.css (file đó đang
  mang việc chưa commit của phiên khác).
- Breakpoint dùng ĐÚNG 680px theo luật 3 ở đầu next.css (hợp đồng với matchMedia
  trong realtime.js). Lượt đầu tôi đặt 900px — đã sửa.
- Test sau thay đổi: 99 passed.

### CHƯA làm — chưa đối chiếu từng phần tử
- Rail: live 452px, design 380px.
- Chưa so nội thất Regime Monitor (thanh xác suất trạng thái: đo ra live KHÔNG có),
  Market View (tab sleeve / lưới slot / biểu đồ giá — live CÓ, chưa so chi tiết).
- Đây không phải "đã quét hết". Còn lệch thì còn, cần một lượt đối chiếu
  từng mục mới nói được hết.

### Cập nhật 3 (2026-09-01): đối chiếu từng phần tử với design
Phương pháp: dựng phép đo trả về CHỖ LỆCH kèm giá trị thật, chạy lặp tới khi
count=0 — thay vì sửa theo cái đập vào mắt.

Đã sửa thêm:
- [x] Ô Now Monitor: một dòng (flex/baseline/gap 9px, đệm 8px 14px), nhãn 10px,
      tên 12px, giờ+khoảng cách dồn phải. Trước đó xếp dọc, đệm 16px 20px.
- [x] Nhãn ô lấy cùng biến màu với vạch accent (skin tô cả 4 nhãn bằng một token)
- [x] Rail 452px -> 380px
- [x] Decision / Positions / Orders: trả lại khung thẻ (viền+bo 8px)
- [x] Hàng chỉ số: 2 cột mặc định, 4 cột chỉ từ 1600px trở lên

Đo được / rút lại:
- KHÔNG cần đụng realtime.js: màu+font bên trong ô đã trùng design sẵn.
- Tôi báo nhầm 3 lần rồi tự rút lại sau khi đo: (a) "regime thiếu thanh xác suất"
  — sai, #regimePosterior có; (b) "Calm thiếu 7/8 nhãn" — sai, nhãn đến từ payload
  (realtime.js:2233 đọc b.gates, 2284 đọc iv.rows), grep vào JS không thấy được;
  (c) "window-bar cao 0 là hồi quy" — sai, skin-e:438 cố ý ẩn.
- skin-e:446 `.section-band > .section-body` đè chính skin-e:681/696, làm hai luật
  card của skin trở thành vô hiệu. Đã đè lại bằng specificity (0,3,0).
- Ép 4 cột theo design ở 1440px làm "0.00%" đè "Protection" — test overlap bắt
  được. Design giả định min-width:1900px; chép cột mà không chép bề rộng là va chạm.
- Lỗi quy trình của tôi: chạy pytest browser NỀN trong khi vẫn lái Chrome vào
  cùng Flask server -> /paper timeout 90s. Chạy lại sạch thì xanh. Không chồng nữa.

Test cuối: 99 passed. Mismatch probe: 0.

### CÒN LẠI (chưa 100%)
- Chưa so pixel từng phần tử bên trong Market View / Regime Monitor / Job journal;
  mới xác nhận CÓ ĐỦ khối và khớp các thuộc tính đã liệt kê.
- Calm hôm nay ở trạng thái "not yet run" (01:5x ET, pha chạy 09:32/10:02) nên
  bảng instrument/gates rỗng — chưa quan sát được bản đầy đủ để so.

### Cập nhật 5 (2026-09-02): ghép hai pha Calm theo mã — XONG
Làm theo trình tự đã cam kết, không bỏ bước nào.

1. Viết test TRƯỚC, chạy -> ĐỎ đúng lý do:
   {'MES': 0, 'MNQ': 0} không panel nào mang riêng một mã kèm cả hai pha;
   tally cổng đọc được [] . Chốt chặn "phải dựng >=2 khối mã" đã qua nên là đỏ
   thật, không phải đỏ vì trang rỗng.
2. realtime.js: thêm mvCalmByInstrument(), xoay vòng lặp phase<->instrument.
   Đường cũ (1 mã) giữ NGUYÊN, chỉ thêm 2 dòng điều phối. Diff = 107 dòng thêm.
3. CSS layout mới đặt ở next.css (skin-e.css đang dở của phiên khác).
4. Chạy lại 2 test -> XANH.
5. Kiểm đột biến: tắt đúng dòng điều phối -> 2 test ĐỎ lại -> khôi phục.
6. preview.html: không có calmSection/track1-section nên không bị chạm; 3 dải
   vẫn đúng, dải 01 tự rút gọn khi thiếu mục; không lỗi console.

Kết quả trên phiên 2026-08-31 (phiên design dựng từ đó):
- 2 panel MES/MNQ CẠNH NHAU (top 4561 = 4561), 4 tiêu đề cột thẳng hàng (4588).
- Mỗi panel: "4 / 4 gates met", nhãn GATES, 7 hàng x 2 cột.
- Bảng tự chứng minh luận điểm design: đúng HAI hàng đổi giá trị ở OBSERVE —
  Entry reference (— -> 7,689.75) và Planned stop (— -> 7,600.21). Các hàng còn
  lại giữ nguyên hai bên.
- 7 hàng thay vì 5 như mockup vì dữ liệu thật tách "Stop rule" và "Entry
  reference time" thành hàng riêng; mockup gộp vào chú thích. Hiện đủ là ĐÚNG.

Hai lỗi tự gây ra rồi tự sửa trong lượt này:
- Vòng đọc/ghi text-mode của bước kiểm đột biến đã đổi CRLF -> LF cả file 264KB.
  git chuẩn hoá nên diff vẫn sạch (107 dòng), nhưng đã trả lại CRLF cho khớp
  hàng xóm. Bài học: kiểm hash sau khi khôi phục, và đọc/ghi nhị phân.
- Thẻ ghép ban đầu chỉ chiếm nửa cột (skin lay .mv2-calm-cards thành 2 cột cho
  2 thẻ pha cũ) nên MES xếp TRÊN MNQ — đúng thứ mà thay đổi này tồn tại để xoá.
  Và vạch ngăn xếp-dọc của skin đẩy panel thứ hai thấp 19px. Đã sửa cả hai.

Test cuối: 101 passed (99 cũ + 2 mới).

Lưu ý cho người sau: test_every_rule_in_the_shared_sheet_actually_wins chạy RIÊNG
mất 103.9s trong khi nó chỉ cho .blocker-card 90s -> vốn đã sát ngưỡng, thỉnh
thoảng đỏ khi server bận. Không liên quan tới thay đổi này (/paper nạp 0 script
từ realtime.js). Nên nâng timeout hoặc làm ấm fixture.

### Files
sửa:  global_index/dash/realtime/realtime.js (+107)
      global_index/dash/realtime-next/next.js, next.css
thêm: monitor/fixtures/track1_market_view_20260831.json (payload THẬT, không bịa)
      2 test trong monitor/test_realtime_skin.py

### (ghi bù) Cập nhật 4 — thuộc về TRƯỚC Cập nhật 5
Lượt ghi này lúc đầu rơi nhầm vào global_index/dash/realtime/TASK.md vì cwd của
shell còn ở thư mục khác. Nối bù vào đây, không sắp xếp lại các mục đã có.

### Cập nhật 4 (2026-09-02): so Calm bằng dữ liệu phiên cũ
Chủ dự án nhắc: không cần chờ 10:02, dùng dữ liệu hôm qua. Đúng.

Cách làm: API /api/v1/track1-market-view CÓ nhận ?day=YYYY-MM-DD và trả `sessions`.
Quét 7 phiên -> 2026-08-31 là ngày đầy đủ (4 instrument, 4 gate, 26 row).
Đó CHÍNH LÀ phiên bản design dựng từ đó.

Kết quả so, dùng 2026-08-31:
- 5 hàng của design (Entry reference / Planned stop / Daily ATR / Stop distance /
  Risk if taken): live có ĐỦ 5.
- 4 gate của design (regime is calm / bottom third / down close / gap not deep):
  live có ĐỦ 4.
- Giá trị MNQ trùng KHÍT design: stop 28,837.21 · ATR 401.20 · dist 601.79 ·
  risk 1,203.59. (Entry reference live 29,439.00 vs mockup 29,429.00 — lệch ở
  mockup, không phải ở trang.)

Bộ chọn phiên: ĐÃ CÓ SẴN, tôi tìm sai selector lần trước. realtime.js:2345
mvDayBar() dựng #marketViewDays thành button.mv2-day, có .thin cho ngày không
diagnostics và <i>today</i> — khớp design. Lúc đầu nó rỗng vì `sessions` chưa nạp.

CÒN LẠI đúng 3 chỗ, và đều thuộc lớp rủi ro KHÁC (phải đổi DOM, không phải CSS):
1. Sắp xếp: live chia theo PHA (2 thẻ DECIDE/OBSERVE, mỗi thẻ liệt kê 2 instrument);
   design chia theo INSTRUMENT (1 thẻ, mỗi instrument có DECIDE|OBSERVE cạnh nhau
   thành 2 cột). Đây là luận điểm của design: "Only the two priced rows change".
2. Thiếu nhãn hàng GATES.
3. Thiếu tally "4 / 4 gates met" mỗi instrument.

Chưa làm 3 mục này. Lý do: realtime.js:2260-2319 dựng cấu trúc đó, file 264KB dùng
chung cho /realtime + /realtime-next + preview.html và vừa commit lúc 20:31 hôm
trước. Đảo vòng lặp phase<->instrument là refactor thật, và realtime.js dựng lại
thẻ này mỗi 8s nên nếu làm trong next.js thì phải có MutationObserver giữ nhịp.
Cần quyết trước khi động vào.

### Cập nhật 6 (2026-09-02): quét có mẫu số, và chỗ bế tắc thật
Chủ dự án: "vẫn chưa 100% giống file html". Đúng. Vấn đề gốc: 5 lượt qua tôi chỉ
so TẬP CON do tôi tự chọn, nên mỗi lượt lại lòi ra chỗ mới. Đổi cách: quét theo
danh sách có mẫu số.

Quét 16 điểm design -> 14 khớp, 2 lệch:
- [x] Regime: live có 5 ô, design có 4. Ô thừa "Shift threshold / None published"
      NÓI LẠI đúng điều mà chú thích ngay dưới đã nói ("No fixed shift threshold:
      the model selects the most likely state by comparing posteriors"). Design bỏ ô,
      giữ chú thích. Đã gập ô — next.js đánh dấu theo NHÃN chứ không theo vị trí, và
      CÓ CHỐT: chỉ gập khi chú thích còn mang sự thật đó, nếu không thì gập = xoá
      mất thông tin chứ không phải khử trùng lặp. Ô vẫn nằm trong DOM.
- [ ] Font selector: design KHÔNG có, live CÓ. KHÔNG gỡ — nó là tính năng thật và
      đang bị test_the_font_control_actually_changes_the_font ghim. Đây là chỗ
      mockup thiếu so với trang, không phải trang thừa so với mockup.

Đã khớp (14): PAPER·NEXT badge, nav 4 mục, 3 phụ đề dải, Open Orders 7 cột đúng
tên, Decision 5 ô + 3 nhóm, Regime posterior/features/60-ngày, Journal 2 tab,
Source Clocks 6 dòng.

Test: 101 passed.

### BẾ TẮC — cần file gốc trên đĩa
Không thể tuyên bố 100% khi chưa diff bằng máy. File design không có trên đĩa
(đã tìm), nên mọi so sánh tới giờ đều qua mắt tôi đọc bản trong hội thoại — đúng
cái khâu tôi đã sai 5 lần.
Chép tay ~2000 dòng (design + support.js) có rủi ro sai lệch âm thầm ở BASELINE;
baseline sai thì mọi kết luận sau đều vô giá trị.
Internet có (unpkg React HTTP 200), nên nếu có 2 file trên đĩa thì render được
bản design và so máy-với-máy, từng phần tử.

### Cập nhật 7 (2026-09-02): so BẰNG MÁY — file design đã có trên đĩa
File nằm ở global_index/dash/ từ 22:24 hôm trước. Tôi tìm một lần lúc đầu phiên,
trượt vài phút, rồi KHÔNG đo lại suốt 6 lượt. Cùng loại lỗi với những lần trước:
kết luận từ một phép tìm âm tính rồi giữ nguyên.

Đã render bản design qua chính server (route /dash/<file>) — React nạp được,
3 dải Operations/Book/Market hiện đủ. So bằng máy, cùng phiên 2026-08-31, cùng
trạng thái (mở một job):
  313 nhãn design | 125 không có trên live | 72 trong đó không phải dữ liệu

Phân loại 72 cái đó (đo từng cái, không đoán):
A. Khác CÂU CHỮ giữa mockup và dữ liệu thật — không phải thiếu:
   "causal, fixed before the open" vs "fixed before the session opened";
   "entry − 1.5 × ATR" vs "entry - 1.5 x daily_atr"; "prior nth close bottom
   third" vs "prior rth close bottom third" (mockup gõ nhầm nth/rth);
   tên job, dòng log, số liệu phiên.
B. ĐÃ LÀM:
   - [x] Thẻ Calm: dòng "N instruments · M rows · K gates each". Đếm từ bảng
         thật -> ra "2 instruments · 7 rows · 4 gates each" (mockup ghi 5 vì gộp
         2 hàng vào chú thích). Chỉ in khi mọi instrument cùng hình dạng, nếu
         không thì bỏ — chữ "each" mà sai là tệ hơn không có.
C. KHÔNG LÀM, có lý do:
   - Crisis (thanh posterior thứ 4): backend chỉ trả Calm/Normal/Stress. Vẽ
     thanh 0.0% là BỊA SỐ. Đây là câu hỏi về DỮ LIỆU (CLAUDE.md ghi HMM 4 trạng
     thái) — đáng kiểm riêng, không phải lỗi dashboard.
   - "Full log" / "Artifacts" / "Re-run" / "Refit": là NÚT HÀNH ĐỘNG, cần
     endpoint backend. Nút bấm không làm gì tệ hơn không có nút.
   - "Show all 66 jobs": live đã hiện CẢ 26 job, không cắt bớt. Mockup mới là
     bản rút gọn. Live đầy hơn, không thiếu.
   - Font selector: design không có, live có + đang bị test ghim. Không gỡ.
D. CHƯA KẾT LUẬN:
   - "Collapse all": job mở rộng được qua button.job-trigger, nhưng phép đo bị
     nhiễu do panel vẽ lại. Chưa làm.
   - Dòng gợi ý "hover a slot to read both charts at the same minute": tương tác
     ĐÃ có (113 điểm hover), chỉ thiếu dòng chữ.

Test: 101 passed.

### Cập nhật 8 (2026-09-02): đóng nốt nhóm D
- [x] Đồng bộ slot qua các lane + dòng đọc. Mỗi ô/slot ĐÃ mang sẵn title do
      realtime.js ghi từ phán quyết thật ("01:10 · gate allow · passed"), nên
      readout ghép TỪ ĐÓ — không nội suy giờ giữa các mốc trục, không bịa.
      Đo: rê slot 3 -> "slot 3 / 22 · 01:20 ET — gate allow: passed · freshness
      allow: passed · regime lag 1: failed · Calm · admission cap result: not
      reached"; 5 ô cùng chỉ số sáng, 2 lane khác lưới bị bỏ qua đúng.
      Listener delegate từ .market-view-section (phần tử tĩnh của trang) nên sống
      qua mọi lượt vẽ lại 8s mà không cần gắn lại.
- [x] "Collapse all": chỉ hiện khi có job đang mở, bấm thì đóng bằng chính
      trigger của trang (không thò tay vào state.selectedJobId của realtime.js).
      Nối vào MutationObserver sẵn có — chạy trong apply() 30s thì nút hiện muộn
      nửa phút, tức là không phải nút. Node là ANH EM của #journal nên không tự
      kích hoạt lại observer.
      Đo đủ chu trình: chưa mở->không nút; mở->hiện; bấm->đóng; nút tự ẩn.

KHÔNG làm dòng chữ y hệt design "hover a slot to read both charts at the same
minute": live chỉ có MỘT vùng biểu đồ, và cả file có đúng 1 listener mouseenter
với 0 luật :hover cho mv2/lane/slot. Dùng câu mô tả đúng việc nó làm:
"hover a slot to line up every rule at the same moment".

Test: 101 passed. Không lỗi console.

### Cập nhật 9 (2026-09-02): so RIÊNG Market View, và một lỗi thật
Chủ dự án hỏi Market View đã đồng nhất chưa. Chưa — tôi chưa từng so riêng mục
này. Đã so bằng máy (design render vs live, cùng phiên 08-31):
  50 nhãn trong Market View của design | 13 thiếu | 8 không phải dữ liệu

LỖI THẬT tìm được và đã sửa (TDD):
- [x] Lane "regime lag 1" in ra `needs ['Normal']` — dấu ngoặc vuông và nháy đơn
      là cú pháp Python lọt thẳng ra bảng vận hành.
      Nguồn: monitor/backend/track1_market_view.py::_threshold_display chỉ có
      nhánh None/dict/bool rồi rơi vào str(raw); một detector publish ngưỡng là
      LIST (các regime được phép) — trường hợp thứ ba mà docstring không lường.
      Chuỗi gốc sinh ở global_index/track1_normal_r4.py:647 (f-string in list),
      nhưng đó là file ENGINE, ngoài tuyến của tôi — sửa ở tầng dashboard.
      Test viết trước, ĐỎ (`assert "['Normal']" == 'Normal'`), sửa, XANH.
      Ghim CÁCH ĐỌC chứ không ghim literal: 1 phần tử -> "Normal";
      2 -> "Normal or Stress"; 3 -> "Calm, Normal or Stress"; rỗng -> "".
      LƯU Ý: server 5002 đang giữ code Python cũ trong bộ nhớ — trang sẽ hiện
      đúng sau khi backend khởi động lại. Tôi KHÔNG tự restart server.

CÒN LỆCH ở Market View, backend ĐÃ có dữ liệu, chưa làm:
- Câu lý do một dòng: design "Every slot decided and none fired. regime lag 1
  failed on 14 of 22 decided slots." Live chỉ có chip, không có câu.
- Cặp bên phải: design `regime lag 1 failed 14 of 22` + `recorded while the
  slots ran`. Nguồn có sẵn: setup_boundary.nearest_failed_condition (gate,
  threshold, value) và setup_boundary.boundary_proof.
- Chú thích cạnh chip phiên: "Sessions on disk. Dim days recorded no per-slot
  diagnostics; their conditions are replayed from bars." Live có tooltip cùng
  nội dung trên từng chip nhưng không có dòng giải thích hiển thị.
- "basket gate then price trigger": design nêu hình dạng luật vào lệnh.

Test: 322 passed (backend + 3 bộ browser).

### Cập nhật 10 (2026-09-02): Market View — đóng hết, và một lỗi lây lan
Dựng môi trường so sạch: chạy server RIÊNG ở cổng 5099 (code Python mới) thay vì
restart server 5002 của chủ dự án.

Đã thêm vào Market View (dữ liệu backend đều có sẵn, không bịa gì):
- [x] Câu lý do dưới chip: "Every slot decided and none fired. regime lag 1 failed
      on 22 of 22 decided slots." Mọi mệnh đề đều có điều kiện riêng — phiên quyết
      18/22 sẽ nói 18/22, phiên không lane nào fail thì không có câu đổ lỗi.
- [x] Cặp bên phải: "<lane> failed N of M" + "recorded while the slots ran" /
      "replayed over stored bars" (đọc has_diagnostics của phiên, KHÔNG suy từ việc
      có lane hay không — replay cũng sinh lane).
- [x] Chú thích chip phiên "Sessions on disk. Dim days…", chỉ hiện khi thật sự có
      ngày mờ trên hàng.
- [x] Chip "Regime → Calm" (trước là "Regime Calm" — hai chữ cạnh nhau không nói
      được chữ nào là luật, chữ nào là giá trị quan sát).
- [x] "Why this label?" — thêm dấu hỏi cho khớp design.
- [x] Đường dóng đồng bộ HAI biểu đồ ở tab Price context + dòng đọc. Mỗi chart
      dùng x RIÊNG của nó cho cùng một slot: đo được mark chạy 341.9→880.7 còn
      series chạy 52→988 (chart giá còn vẽ bar trước cửa sổ), nên dùng chung một
      tỉ lệ sẽ đặt hai đường vào hai phút khác nhau — đúng lỗi mà tính năng này
      sinh ra để chống. Nhờ đó câu y hệt design "hover a slot to read both charts
      at the same minute" giờ ĐÚNG SỰ THẬT.

LỖI LÂY LAN, sửa bằng một cổng chứ không vá từng chỗ:
- Ba lần vá ba trường (threshold_display -> setup_boundary -> strategy.detail) mà
  trang vẫn còn repr Python là dấu hiệu đang đuổi triệu chứng. Đặt cổng ở CHỖ RA
  của build(): không chuỗi nào trong payload được mang cú pháp list của Python.
  Danh sách thật giữ nguyên kiểu (threshold: ["Normal"]).
  Chỉ chuẩn hoá LIST LITERAL, cố ý không đụng nháy đơn trong văn xuôi — ghép cặp
  nháy trong "today's … tomorrow's" sẽ nuốt mất nửa câu.
  Nguồn gốc vẫn ở engine (track1_normal_r4.py:647), ngoài tuyến của tôi.
- Đo sau khi sửa: 0 list-literal trong payload; 0 trên trang (text + tooltip).

Market View sau cùng: 50 nhãn design, còn 4 khác biệt và cả 4 là CỐ Ý —
mockup sai (basket gate / nth-vs-rth), live giàu hơn (declared, hiện đủ job),
hoặc live lấy tên từ nguồn thật hơn (Regime vs tên lane).

Test: 324 passed.

### Cập nhật 11 (2026-09-02): so bằng ẢNH, không phải bằng chữ
Chủ dự án: "chụp screenshot rồi so đi... padding, regime monitor, chart bị stretch".
Đúng — 10 lượt trước tôi so NHÃN CHỮ, không so hình.

Lỗi phép đo bắt được ngay đầu: hai trang đang ở hai bề rộng khác nhau
(design 2033, live 1887) vì lệnh resize chỉ ăn ở một tab. Mọi số hình học đo lúc
đó KHÔNG so được. Đưa live về 2035 rồi mới đo — section rộng 1654 vs 1652, khớp.

Sửa được (đo trước, đo sau):
- [x] Model Inputs nằm SAI CHỖ: design đặt nó là hàng đầu BÊN TRONG thẻ regime;
      lần trước tôi nhắm .section-body (section này không có) nên nó rơi ra ngoài
      khung, nổi trên tiêu đề. Nay prepend vào .rg2-card + style thành dải trên
      cùng có vạch ngăn. Đo: modelInputsInCard = true.
- [x] CHART BỊ STRETCH — nguyên nhân thật không phải chiều cao mà là TRỤC X:
      chart giá giữ 22 slot trong khoảng 341.9→880.7, còn chart chuỗi trải
      52→988. Cùng một slot nằm ở 47% của chart trên và 5% của chart dưới, nên
      hai chart không thẳng hàng dọc và đường chuỗi bị kéo qua phần bề rộng mà
      nến không hề dùng. Nay chart giá công bố khoảng x thật của slot
      (mvSlotSpan) và chart chuỗi dùng lại — CHỈ khi số slot khớp, vì span của
      một chart khác số slot sẽ ghép hai bên vào hai phút khác nhau.
      Đo sau: cả hai đều 341.9→880.7, aligned = true.
- Chiều cao: đo ra vùng giá live 214px vs design 210px (padT16+giá214+vol44+padB46
  = 320). Gần khớp; KHÔNG ép CSS xuống 268 vì viewBox vẫn tính cho 320 nên sẽ
  bóp méo hình. Chênh còn lại nằm ở vùng volume (44 vs 58) và lề trục.

Test: 324 passed.

### Cập nhật 12 (2026-09-02): quét HÌNH HỌC toàn bộ 11 mục
Dựng bộ đo chạy CÙNG MỘT logic trên cả hai trang (tìm mục theo tiêu đề, leo lên
container, đọc padding/bề rộng/chiều cao từng hàng), rồi diff bằng máy.

Bắt được 4 chỗ lệch, sửa cả 4:
- [x] Bốn thẻ chỉ số: design dùng CHUNG một đệm 11px 15px; live cho equity
      16px 18px và ba thẻ kia 12px 16px — hàng bốn thẻ không có nhịp chung, chữ
      trong thẻ đầu bắt đầu ở một mức, ba thẻ sau ở mức khác.
      Sau: cả bốn 11px 15px, rộng 459/367/367/367 (design 462/370/370/370),
      cao 176 (design 175).
- [x] Now Monitor: 18px 22px -> 16px 22px (design cho mục mở đầu cột đệm trên hẹp hơn)
- [x] Open Orders: 18px 22px -> 18px 22px 24px (đóng nhóm 01, khoảng nghỉ trước
      dải 02 rộng hơn khoảng giữa hai mục cùng nhóm)
- [x] Source Clocks: tiêu đề 17px -> 15px (mục phụ trong rail, không tranh chấp
      với Job journal ngay trên nó)

BẪY PHÉP ĐO tự bắt: bảng so vòng đầu báo Performance/Risk/Exposure lệch
"22px 26px 0px" — sai, vì bộ dò leo lên phần tử CHA chứ không đo chính thẻ.
Đo trực tiếp từng thẻ mới ra 12px 16px. Nếu tin bảng đầu thì đã sửa theo số sai.

Quét lại sau khi sửa: 11/11 mục khớp padding và bề rộng — SỐ CHỖ LỆCH = 0.
Test: 324 passed.

### Cập nhật 13 (2026-09-02): quét TOÀN BỘ hệ thị giác, không chỉ đệm
Mở rộng bộ đo sang màu, bề dày viền, bo góc, cỡ/độ đậm/giãn chữ, gap. Lập danh
mục giá trị trên cả hai trang rồi diff.

KHỚP SẴN, 0 lệch: bo góc, bề dày viền.

Sửa được:
- [x] font-weight: design chỉ dùng 400/500/600. Live dùng 700 ở 22 chỗ — một bậc
      nặng hơn cả hệ, nên nhãn phụ (Problem/Impact/Action/Evidence, chip cổng,
      chip market view, tên instrument) đòi chú ý ngang tiêu đề mục.
      Sau: 400/500/600, 700 = 0.
- [x] Cỡ chữ lẻ 9.92px và 9.16667px — không phải giá trị ai chọn, rơi ra từ em
      chồng em. Đưa về bậc 10px của design. Sau: 0 cỡ lẻ.
- [x] Con số equity 40px -> 30px (design). LỖI THẬT: skin-e đặt
      `.equity-line > b { font: 500 40px/1 }` CÙNG specificity với luật 26px của
      next.css nhưng nạp sau, nên luật của next.css VÔ HIỆU TỪ ĐẦU — đúng cái bẫy
      mà đầu next.css đã cảnh báo về chính nó.
- [x] Con số rủi ro 22px -> 24px (design).

BA LẦN ĐOÁN SAI SPECIFICITY, đều tự bắt bằng đo:
chip cổng vẫn 700 sau khi thử `.t1-gates > .t1-gate` rồi
`.now-schedule-facts .t1-gates > .t1-gate`. Đo ra luật thắng là
`#track1Facts .t1-gate` — một ID (1,1,0), mọi selector ba-class đều thua.
Bài học: đọc luật đang thắng trước, đừng leo thang specificity bằng cảm giác.

CÒN LỆCH, chưa xử:
- letterSpacing: nhiều giá trị nhỏ khác nhau hai bên (phần lớn do em quy đổi).
- gap: live dùng nhiều giá trị design không có (5px 8px x28, 5px x18, 20px x8...).
- màu: chưa diff (danh mục đã thu nhưng chưa đối chiếu).
- .system-conclusion 22px vs design 15px: CỐ Ý CHƯA ĐỔI — next.css có lý do đo
  được ("hai số lớn nhất đều nói 'fine' trong khi kết luận sức khoẻ ở 13px").
  Đổi theo design sẽ hạ chính dòng phán quyết. Cần chủ dự án quyết.

Test: 324 passed.

### Cập nhật 14 (2026-09-02): dòng phán quyết + ba tab Market View
- [x] .system-conclusion 22px -> 15px/500/-.005em theo design. ĐÂY LÀ ĐẢO một
      quyết định có đo đạc ở khối E1 của next.css ("hai số lớn nhất đều nói fine
      trong khi kết luận sức khoẻ ở 13px"). Chủ dự án đã quyết theo design.
      Phần bù giữ nguyên: hình dạng chấm trạng thái + nhãn OK/WARN/FAIL ở khối A2
      vẫn còn, nên trạng thái đọc được không cần dựa vào cỡ chữ.

Thanh ba tab — đo được 4 lệch, sửa cả 4:
- [x] nền thanh rgb(14,17,22) -> rgb(11,13,17)
- [x] đệm tab 6px 14px -> 5px 13px
- [x] hàng chứa thanh: đệm 0 -> 8px 15px, gap 10px -> 12px
      (đệm 0 làm thanh dính sát mép thẻ, lệch nhịp với mọi dải khác trong thẻ)

Pane "Setup rules":
- [x] lưới lane 212px/1fr/126px -> 246px/1fr/110px (nhãn luật bị bó, cột tổng thừa)
- [x] ô 12px -> 10px
- [x] màu vạch ngăn -> #171b22
- [x] chú giải 11px 18px/gap 16px -> 7px 15px/gap 18px

Pane "Detector rules": dùng CHUNG class .mv2-lane nhưng design cho thang nhỏ hơn
(một ô = một BAR, nhiều hơn số slot). Tách bằng container .mv2-bargrid:
- [x] lưới 246px/1fr/110px, ô 9px, bo 1px

Pane "Price context":
- [x] dòng đọc hover: bọc khung 1px/bo 6px/nền deep/đệm 7px 12px như design —
      nó là vùng ĐỌC đổi theo con trỏ, không phải chú thích.
- (đã làm ở lượt trước: hai chart cùng trục x 341.9->880.7)

Đo sau: Setup 246/1fr/110 ô 10px viền rgb(23,27,34) chú giải 7px15px/18px;
Detector 246/1fr/110 ô 9px bo 1px; thanh tab nền rgb(11,13,17) đệm 5px13px
hàng 8px15px/12px; phán quyết 15px. Không tràn ngang.

Test: 324 passed.

CÒN LỆCH đã biết, chưa xử: gap (live dùng nhiều giá trị design không có),
letterSpacing, và danh mục MÀU chưa đối chiếu.

### Cập nhật 15 (2026-09-02): hành vi tab + style nội dung 3 tab
LỖI HÀNH VI (chủ dự án phát hiện): bấm tab nào cũng hiện Setup prerequisites và
Across the session. Đo được: #marketViewSetup (708px) và .mv2-slotchart (279px)
render ở CẢ BA tab -> tab trở thành trang trí.

Không suy từ đọc file: BẤM từng tab trên bản design render và ghi lại nó hiện gì.
  Setup rules    : lanes + slot decisions + legend
  Detector rules : per-bar grid + Conditions + Readings + Nearest miss + Trade levels
  Price context  : price chart + across the session
- [x] Sửa realtime.js theo đúng bảng đó. Giữ nguyên nhánh KHÔNG có tab strip
      (không có gì để chọn thì panel giữ hình cũ và mang tất cả).
- [x] Đo sau: live trùng khít bảng của design, cả 3 tab.

Style nội dung 3 tab (diff danh mục style theo TỪNG pane):
- [x] Thanh tab: nền, đệm tab, đệm+gap hàng chứa (4 chỗ)
- [x] Setup rules: lưới lane 246/1fr/110, ô 10px, màu vạch ngăn, chú giải 7px15px/18px
- [x] Detector rules: tách bằng .mv2-bargrid — ô 9px, bo 1px (một ô = một BAR,
      nhiều hơn số slot nên thang phải nhỏ hơn)
- [x] Price context: 4 đường về đúng màu/nét design (EMA tím->xanh dương,
      đường trung bình khối lượng XANH LÁ->xám: xanh lá trên bảng này đã mang
      nghĩa "đạt" ở lane và nến, một đường xanh lá không mang phán quyết nào là
      mượn nhầm nghĩa); thêm vùng tô gradient dưới đường close, dựng từ CÙNG các
      đoạn với đường nên đứt ở đâu tô đứt ở đó.
- [x] Thang xám: design chỉ có 2 tông (#798394, #4b5563). Live có #798394 sẵn
      dưới tên --t-label nhưng --dim = #728392 và --t-faint CHƯA TỒN TẠI, nên
      ba tông xám cùng xuất hiện trên một thẻ. Đặt --dim=#798394, --t-faint=#4b5563.
      KHÔNG hạ tương phản: #798394 sáng hơn #728392 trên nền tối, khối A5 vẫn được
      tôn trọng.

SUÝT SỬA NHẦM: dải WINDOW live là xanh sáng ở opacity .06 -> ra rgb(18,26,36),
gần trùng rgb(16,26,44) của design. Đo trước khi sửa nên không đụng vào.

Test: 324 passed (chạy gộp). Một lượt gộp trước đó treo + 1 F nhất thời; chạy
riêng từng bộ đều xanh (223 + 39 + 62 = 324) rồi gộp lại xanh.

### Cập nhật 16 (2026-09-02): đóng hai trục gap và letterSpacing
letterSpacing — BÀI HỌC PHÉP ĐO: diff theo px lúc đầu báo hàng chục chỗ lệch,
nhưng đo lại theo EM thì phần lớn là DƯƠNG TÍNH GIẢ (px khác nhau chỉ vì cỡ chữ
khác nhau). Theo em chỉ còn 17 phần tử thật sự ngoài thang.
- [x] .issue-scope, .mv-tab -> .1em (cùng vai "nhãn chữ hoa nhỏ")
- [x] .mv2-src -> .12em ; .mv2-sc-day + hai dòng đọc hover -> .06em
      (hai dòng đọc là của tôi thêm ở lượt trước, tôi đặt .04em — không có
      trong thang design)
- Còn 5: -0.015 x1, 0.050 x2, 0.020 x2 — vai lẻ, chưa map được sang design.

gap — KHÔNG ép mù cả thang: design có ~17 giá trị gap khác nhau, không phải một
bộ token chặt. Chỉ chỉnh vai trò đếm được và map được:
- [x] .section-heading 20px -> 12px (8 đầu mục; đặt nhịp ngang toàn trang)
- [x] .job-trigger 5px 8px -> 7px (29 phần tử, nhiều nhất trang)
- [x] chú giải .mv-legend-item/.mv2-sc-key 5px -> 7px, .regime-legend-item -> 6px
- [x] .issue-badges -> 7px, .now-monitor-list/.open-issue-list -> 8px,
      .mv2-daybar -> 6px
- Đo sau: 28 -> 22 chỗ ngoài thang.

DỪNG Ở ĐÂY CÓ CƠ SỞ, không phải vì thấy đủ: 22 chỗ còn lại nằm trên cấu trúc mà
design KHÔNG CÓ — .issue-list-row (lưới, design dùng thẻ phẳng), .model-input-item
(cặp flex, design dùng padding+border), .zone-grid, .rg2-feats, .regime-rowhead,
.mv2-verdict, .system-facts. Ép chúng về một giá trị của design là gán số cho
phần tử không có đối chứng, tức đoán chứ không phải khớp.

LỖI SPECIFICITY LẦN THỨ BA trong phiên: luật ngang specificity với skin-e mà
skin-e nạp sau -> thua. Lần này bắt bằng cách đọc luật đang thắng trước khi sửa,
không leo thang bằng cảm giác.

Test: 324 passed.

### Cập nhật 17 (2026-09-02): ba lỗi hình học chart + phương pháp quét
Chủ dự án hỏi: "làm ntn để chính xác toàn bộ tất cả các elements?"

VÌ SAO BỘ ĐO CŨ BỎ SÓT. Nó so GIÁ TRỊ THUỘC TÍNH (màu/cỡ/đệm/gap) giữa hai trang.
Nó không thấy được ba loại lỗi khác, và cả ba đều có mặt ở đây:
  thiếu phần tử   -> phải ĐẾM phần tử theo vai ở hai bên rồi so số lượng
  biến dạng       -> phải đo KÍCH THƯỚC TRÊN MÀN HÌNH, không đọc thuộc tính SVG
  sai tương tác   -> phải BẮN sự kiện chuột theo lưới toạ độ và ghi phản hồi

Đã sửa:
- [x] Chấm bị kéo giãn: preserveAspectRatio="none" -> scale x 1.607, y 1.0, nên
      mọi <circle> thành ellipse (đo: 10.9 x 6.8px). Đổi sang <ellipse> mang bán
      kính MUỐN THẤY, next.js chia rx theo scale ĐO ĐƯỢC (không hardcode tỉ lệ:
      chiều cao pane đang ghim 320px nhưng nếu đổi thì y cũng giãn, và tỉ lệ viết
      cứng sẽ không nói ra điều đó). Sau: 74/74 chấm tròn.
      Phải gắn MutationObserver: realtime.js vẽ lại mỗi 8s còn lớp này chạy 30s,
      nên phần lớn thời gian rx bị xoá.
- [x] Thiếu marker: design có chấm trên CẢ BỐN đường, live chỉ có ở bar volume.
      Thêm close/ema/avgv. Điểm ĐO tô đặc, đường DẪN XUẤT rỗng ruột viền màu —
      nhìn là biết chấm nào là số đọc được, chấm nào là kết quả tính.
- [x] Hover chỉ ăn khi trỏ trúng chấm 10.9x6.8px. Design có cột trong suốt cao
      hết chart. Làm bằng mousemove + tìm slot GẦN NHẤT theo cx của mark, không
      chèn node (chart bị vẽ lại mỗi 8s, node chèn sẽ phải tái tạo liên tục).
      Đo: rê ở 30% chiều cao, cách mọi chấm -> vẫn bắt đúng slot.

CHỐT CHẶN CŨ ĐÃ LÀM ĐÚNG VIỆC: crosshair chart chuỗi không vẽ, vì polyline chỉ có
13 điểm cho 22 slot (9 slot không có số đọc) và luật cũ TỪ CHỐI ghép theo chỉ số.
Nếu nó ghép bừa thì hai đường dóng lệch nhau 9 slot. Sửa đúng cách: realtime.js
KHAI BÁO data-xspan="shared" khi chart chuỗi thật sự dùng trục của chart giá, và
next.js chỉ dùng chung x khi thấy khai báo đó — không suy đoán từ DOM.
Đo sau: 3 lượt rê, cả hai chart cùng x, khớp cx của mark.

PHÉP ĐO CỦA TÔI SAI MỘT LẦN và tự bắt: báo mark lệch tâm nến 51.3 đơn vị, do tôi
ghép N mark với N bar CUỐI. Ghép lại theo bar gần nhất: lệch 0.00 cho cả 22.

Test: 324 passed.

### Cập nhật 18 (2026-09-02): quét ĐẾM PHẦN TỬ THEO VAI
Dựng bộ đo thứ ba (sau diff nhãn và diff hình học): phân loại mọi phần tử HIỂN
THỊ theo VAI HÌNH DẠNG rồi so số lượng hai bên, cho cả trang và từng tab.

HAI LỖI TRONG CHÍNH BỘ ĐO, tự bắt và sửa trước khi tin số:
1. Phân loại theo THẺ nên so nhầm loại: design vẽ nến bằng div, live vẽ bằng
   <rect>. Cùng một vật rơi vào hai ô khác nhau -> "Price context thiếu hẳn bar"
   là dương tính giả. Sửa: phân loại theo hình dạng trên màn hình, không theo thẻ.
2. Đếm circle/line/polyline TRƯỚC khi kiểm kích thước, nên chart của tab đang ẨN
   vẫn được cộng vào tab đang mở (Setup rules ra dot=101, series=5). Sửa: kiểm
   hiển thị trước, cho mọi thẻ.

Sau khi sửa, bộ đo cho ra MỘT phát hiện cụ thể:
- [x] Ô mẫu trong chú giải: design 10x4px, live 11x9px. Đổi kích thước, GIỮ cách
      live dựng (ô mẫu dùng chính class .mv2-cell nên đổi màu ô thật là chú giải
      tự theo — design hardcode, live tự bảo trì tốt hơn).

GIỚI HẠN CỦA BỘ ĐO NÀY, nói thẳng: nó quá thô với phần tử biểu đồ. Nến cao 30px
rộng 14px không rơi vào ô "bar" theo ngưỡng nào hợp lý, nên các số bar/dot ở tab
Detector và Price context là ARTIFACT của bộ phân loại chứ không phải phát hiện.
Không tinh chỉnh thêm: đến lúc này tôi đang đo chính công cụ của mình.

'control design=0 live=13' KHÔNG phải lỗi: design dùng div có onClick, live dùng
<button> — cùng vai, và <button> đúng hơn về khả năng truy cập.

Test: 324 passed.

### Cập nhật 19 (2026-09-02): quét NỐT 7 mục còn lại
1. BỀ RỘNG KHÁC — đóng bằng phép đo, không cần quét: bản design khai
   `min-width: 1900px`, dưới 1900 nó chỉ CUỘN NGANG. Nó KHÔNG có bố cục hẹp nào,
   nên ở 1440/390 không có gì để so. Phần hẹp là của live và đã được ghim bằng
   test (overflow/clipping/overlap ở đúng hai khổ đó, đều xanh).
2. TRẠNG THÁI KHÁC — bản design chỉ có MỘT trạng thái cố định, nên ngày xấu
   (broker chết, sự cố mở, tín hiệu bắn) KHÔNG có đối chứng trong design.
   preview.html tồn tại chính cho việc đó; đã kiểm nó vẫn dựng đúng 3 dải,
   không lỗi console.
3. BA SLEEVE — live đọc instrument/window từ payload thật; mockup gõ tay cfg.
   NKD 01:10 (design 01:20), Stress MNQ 10:35 (design MES 09:35), Swing MES
   14:05-15:55 (design M2K 09:35). Live ĐÚNG — Swing 14:05 khớp cửa sổ Track 1
   trong tài liệu dự án. Stress có 13 lane vì detector thật publish 13 luật;
   mockup rút còn 4. Không tràn ngang ở cả ba.
4. :hover — cả 6 vai design có style-hover thì live đều có luật :hover. Không thiếu.
5. THẺ JOB MỞ RỘNG — live có Started/Completed/Duration/Outcome/Problem/Impact/
   Action/Evidence; design có Started/Exit/Outcome/Log + 3 nút. Live giàu hơn ở
   phần đánh giá, THIẾU khối Log (cùng họ "cần backend").
6. STICKY — live static, design cũng static. Không lệch.
7. ANIMATION — TÔI ĐO SAI RỒI TỰ SỬA: quét trong `main` mà header nằm NGOÀI main,
   nên báo nhầm là lệch. Đo lại: live có rn-live 2.4s ở header, TRÙNG ĐÚNG lp
   2.4s của design. Khác duy nhất là scheduler-pulse 1.5s trong journal —
   GIỮ NGUYÊN, vì realtime.css:154 chỉ chạy nó khi .fact-scheduler.ok: nhấp nháy
   MANG NGHĨA "đúng lịch", đứng yên khi bad/watch. Gỡ đi là xoá thông tin.

Test: 324 passed (không đổi code sau lượt chạy trước).

### Cập nhật 20 (2026-09-02): G1–G5 theo đặc tả
Ràng buộc giữ đúng: realtime.css KHÔNG đụng (git sạch). Mọi id giữ nguyên —
test_every_element_the_script_writes_to_is_on_the_page vẫn xanh.

- [x] G1 chip ngày: mvPriceHead "bars · <ngày>" (cả hai nhánh return), mvSlotChart
      "slots · <ngày>". Dùng lại class .mv2-sc-day. Trường rỗng thì BỎ HẲN chip.
- [x] G2 lệch phiên: so bars_session_date với strategy.slot_series_session; khác
      nhau thì in mv2-tabnote đầu pane series. Đo: hai ngày trùng -> note KHÔNG
      xuất hiện (lần đo đầu tôi báo có, do selector bắt trúng 2 note sẵn có).
- [x] G3 trục riêng: publishAxisMode() đặt data-xaxis lúc RENDER, không phải lúc
      hover — nhãn chỉ hiện sau khi đã rê chuột là trả lời sau khi người ta thôi
      hỏi. shared -> dóng cả hai pane; own -> không dóng, next.css in nhãn.
- [x] G4+G5 pill chỉ còn <i><b>word</b>; .mv2-verdict-side thay bằng
      .mv2-verdict-meta 5 span có điều kiện. Đo: đúng thứ tự, span đầu không
      border-left, màu #a8b1c0 / #f0b429 / #4b5563 đúng đặc tả.
- Dọn kèm: gỡ seriesXFor (không ai gọi sau G3) và toàn bộ luật .mv2-verdict-side,
  .mv2-prov. Nâng bảng boundary thành hằng MV_BOUNDARY_WORD dùng chung cho
  mvChips và mvVerdict thay vì chép — bản sao thứ hai là bản sẽ trôi.

KIỂM THEO YÊU CẦU
- hover ở cả ba inner tab: không throw. Detector không highlight — ĐÚNG design
  (pane per-bar của design không có hover).
- sleeve KHÔNG có diagnostics (08-28, 08-27): 0 lỗi, verdict + meta vẫn dựng,
  data-xaxis tự gỡ vì không có pane chuỗi. Không tràn ngang.
- Test: 324 passed.

measure_dashboards.py — BA ĐIỀU PHẢI NÓI
1. Công cụ GHI ĐÈ hai file được theo dõi (DASHBOARD_BASELINE.json/.md). Tôi không
   lường trước; đã git checkout trả lại sau MỖI lần chạy.
2. Viewport của nó ghim (1900,1000) và (390,844) — KHÔNG có 1440x900 và 1920x1080
   như yêu cầu. Tôi KHÔNG sửa công cụ (dùng chung, bộ viewport là lựa chọn có
   chủ đích).
3. @1900: 0 chữ-đè-chữ, 0 cắt mép, 0 tràn trang.
   @390 : 3 chữ-đè-chữ, đều ở dải chạy regime
          ('1d | Normal · 9d' x2, 'Normal · 9d | Calm · 15d').
   CHƯA KẾT LUẬN được là mới hay cũ: chạy HEAD hai lần trong cùng harness thì
   trang rơi vào trạng thái "Monitor backend unavailable" và KHÔNG dựng dải đó,
   nên không có mốc so cùng dữ liệu. Luật duy nhất của tôi chạm khu regime là
   #regimeMetrics > .is-restated (ẩn một Ô CHỈ SỐ), còn dải chạy do realtime.css
   style — file tôi chưa từng đụng. Test 390x844 của repo vẫn xanh.
   => Ghi là CHƯA GIẢI QUYẾT, không ghi là "không có overlap mới".

════════════════════════════════════════════════════════════════════════════
ĐỌC DESIGN_SPEC.md (việc phần 4 bắt làm TRƯỚC, tôi đã bỏ qua) — 2026-09-02
════════════════════════════════════════════════════════════════════════════
Đọc mục 6 "Điều KHÔNG được làm" ra ngay một luật đang bị vi phạm, thứ mà cả ba
thước tự chế trước đó đều không thấy.

LUẬT 6.5 — không dùng <text> trong SVG preserveAspectRatio="none".  ĐÃ VI PHẠM
- Đo: pane giá kéo ngang 1,606 / dọc 1,000, bên trong có 15 <text>. Nhãn giá
  rộng 82,8px trong khi bề rộng đúng của nó là 51,6px.
- Vì sao spec cấm thẳng thay vì đặt mức méo cho phép: bản design KHÔNG vẽ chữ
  trong pane. Trục của nó là một cột HTML 72px bên cạnh, bars là <div> tuyệt
  đối. Cả file design có 0 thẻ <text>. Không có chỗ nào méo được.
- Sửa (next.js, không đụng realtime.css): phản-scale ngang từng nhãn quanh
  chính x của nó, k = sy/sx — cùng phép đã dùng cho chấm slot (rx = ry*sy/sx).
  Scale quanh điểm neo nên giữ nguyên vị trí cho cả anchor start lẫn middle.
  Hàm roundDots -> undoPaneStretch (3 call site) vì nó không còn chỉ làm chấm.
- Nghiệm thu: 15/15 nhãn về đúng dáng; trôi vị trí tối đa 0,16px (dưới 1 pixel,
  là bearing của chữ "Window"), 0,00 cho phần còn lại.
- Mutation: gỡ transform ra thì 1,606-1,627 — đỏ. Hai thước độc lập
  (tham chiếu HTML dựng lại, và getComputedTextLength của SVG) ra cùng con số
  tới 6 chữ số thập phân.
- Ghim: test_a_chart_label_is_not_stretched_by_the_pane_it_sits_in.
  75 passed (skin + dom).

BA LẦN THƯỚC SAI TRƯỚC KHI ĐO ĐÚNG — cả ba đều tự bắt được, ghi lại để khỏi lặp
1. "trôi 1530px" — do có await giữa hai lần đo, dashboard render lại, node cũ
   rời DOM và rect của node rời DOM là 0. Dấu hiệu: bốn nhãn ở bốn y khác nhau
   ra CÙNG một con số.
2. "trôi 9,76px" — text-anchor của nhãn giờ đặt bằng CSS chứ không phải
   attribute, getAttribute trả null nên tôi so mép trái của chữ middle-anchor.
   9,76 đúng bằng NỬA chênh lệch bề rộng.
3. "nhãn Window lệch 18%" — tham chiếu HTML của tôi thiếu text-transform, nên
   nó đo "Window" còn SVG vẽ "WINDOW" trên font tỉ lệ.
Và một lần chốt bảo vệ tự cứu: ở 1440px pane chỉ lệch 1,011 lần nên test gần
như không còn gì để bắt -> đặt viewport 1900 (khổ design). Không có chốt đó thì
test xanh mà không kiểm gì.

NGƯỠNG lấy từ số đo, không chọn cho vừa: nền nhiễu 2,6% (hằng số, đo được y hệt
ở skew 1,0 lẫn 1,471 nên KHÔNG phải độ méo) so với tín hiệu +47%.

CÁC LUẬT CÒN LẠI CỦA MỤC 6
- Đạt: 3 (đã có test xanh), 7 / 8 / 9 (chính là G4 / G3 / G5).
- 1, 2, 4, 6: sàng của tôi có nổi cờ (6 bậc xám / 4 metric xếp dọc / 7 section
  quá hai nền) NHƯNG sàng không phân biệt được chip theo tone — mục 1.77 cho
  phép chip có nền màu — với nền của section, và chưa lấy định nghĩa
  "metric compact" từ spec. CỜ TỪ SÀNG LÀ NGHI NGỜ, CHƯA PHẢI KẾT QUẢ.
  => CHƯA KIỂM. Không ghi là đạt, cũng không ghi là vi phạm.
- Chưa đọc: SECTION_ANATOMY.md (11 section), DESIGN_SPEC mục 7 và 8.

════════════════════════════════════════════════════════════════════════════
VÒNG 2 — G1..G5 + đếm lại luật 1/2/4/6 — 2026-09-02
════════════════════════════════════════════════════════════════════════════

ĐO TRƯỚC KHI LÀM: ROUND_2.md mục A1 ghi "G1–G5 chưa làm". Sai — cả năm đã nằm
trong code (mv2-verdict-meta :1909, mv2-sc-day :2246 và :2841, dayMismatch :2832,
data-xspan :2853, next.js :432). A1 là mô tả đã trôi khỏi thứ nó mô tả. Việc thật
của vòng này là đối chiếu GIÁ TRỊ với spec, không phải dựng lại.

ĐÃ SỬA (tất cả trong next.css, không đụng realtime.css)
- Gốc: --mv-dim và --mv-fg KHÔNG được khai ở đâu cả. 15 chỗ trong realtime.css
  dùng chúng, cả 15 rơi vào fallback #8b929c / #d7dbe0 — hai bậc xám ngoài bảng
  bốn bậc. Khai ở :root, sửa cả 15 chỗ bằng một chỗ.
- muc 4.2 session picker: chip đang chọn từ nền SÁNG #d7dbe0 chữ gần đen -> nền
  #14251f, chữ #8ae6cc, viền #1e3a30. Nhãn "Session" và chip thin -> #4b5563.
  Chip ngày khác -> #a8b1c0 / viền #1e242c. padding 4px 10px, radius 5px.
- muc 4.3: pill từ sans 14px -> mono 12px/600/.1em; padding 4px 12px, radius 5px.
  Câu lý do từ primary -> #a8b1c0 và thêm max-width 88ch.
- muc 4.7: chip ngày hai pane từ sans 10px -> mono 11px/.06em, padding 2px 8px,
  viền #262d36, radius 4px.

ĐẾM LẠI BỐN LUẬT — VÀ HAI LẦN SPEC TỰ MÂU THUẪN
Luật 1 (bậc xám chữ)
  Cách đếm của spec KHÔNG DÙNG ĐƯỢC: "HSL saturation <= 6%" loại bỏ đúng bốn màu
  mà chính spec liệt kê là hợp lệ — #e8ebf0 ra 20,8% · #a8b1c0 16% · #798394 11%
  · #4b5563 14%. Đếm đúng như viết thì kết quả LUÔN bằng 0, tức phép đếm không
  thể đỏ. Đã đếm bằng biên độ RGB tuyệt đối (<= 27, giữ đúng bốn màu ấy).
  TRƯỚC: 3 màu ngoài bảng, 10 lần.  SAU: 0. Đạt.
Luật 2 (không tô màu số tiền/số lệnh)
  0 vi phạm trong phạm vi luật. 01/02/03 của group band mang màu accent là muc 2
  YÊU CẦU, không phải vi phạm. +0.82% là PnL, ngoại lệ 1.
  Hai ca để người đọc quyết, không tự kết luận:
  - 0.3922 đỏ ở .mv2-cond-val.bad ("needs <= 0.3333"): số đo mang màu pass/fail.
    Không phải giá/stop/side/qty nên ngoài phạm vi luật; màu chính là thông điệp
    nên hợp ngoại lệ 2. Nhưng CHỮ của ngoại lệ 2 nói "trạng thái, không phải số
    đo" — chữ và tiêu đề của luật lệch nhau ở đúng ca này.
  - "+1" (#71849a) trên dải ba đồng hồ: rơi vào KHE giữa hai luật. Biên độ 41 nên
    luật 1 không tính là xám; không phải tiền/lệnh nên luật 2 không tính. Một tông
    xám-xanh thứ năm mà không phép đếm nào chạm tới.
Luật 4 (metric compact không xếp dọc): 0 vi phạm thật.
  Sàng ra 23. Loại 11 ô giá-trị-là-câu còn 12, và cả 12 nằm trong Track 1 Runtime
  (7) và Regime Monitor (5) — đúng hai nhóm muc 6 ghi là "đừng soi". Cả con số cũ
  (4) lẫn con số mới (23) đều là dương tính giả. Nguyên nhân: --font-ui của repo
  CHÍNH LÀ Cascadia Mono, nên điều kiện "con thứ hai là mono" đúng với cả câu văn.
Luật 6 (không quá hai nền/section): 0 vi phạm. Dự đoán ở A2 đúng — "7 section"
  hoàn toàn là do đếm chip.

CHƯA SỬA, BÁO LẠI
- Luật 7: 5 chip quá 2 từ, đều là .mv-chip ở mv2-head — "Entry after setup bar"
  (4 từ), "Latest 15:54 ET", "Strategy levels unavailable", "Regime -> Calm",
  "Stored session 2026-09-01". Ba trong số đó nay TRÙNG với hàng metadata G4.
  Gỡ chip là quyết định về nội dung, không nằm trong danh sách việc.
- Luật 5 còn nợ phần CẤU TRÚC: bản sửa vòng trước phản-scale chữ nên nhìn đã
  đúng, nhưng tiêu chí kiểm được của spec là `svg[preserveAspectRatio=none] text`
  phải RỖNG, và nó vẫn trả 15. Đưa trục ra cột HTML như design là việc riêng.
- muc 4.3 mô tả verdict là "hàng đầu TRONG CARD" (padding 11px 15px, viền đáy,
  nền inset). Thực tế nó là con trực tiếp của section. Bọc card là thay đổi cấu
  trúc ngoài danh sách việc.
- .decision-retired: đã hết vi phạm nhờ khai token ở :root.

KIỂM BẰNG THƯỚC NÀO
- measure_dashboards.py hai lần CÙNG BUỔI: va chạm 0->0 ở cả 1900 và 390; cỡ chữ
  12->12 (@1900) và 11->11 (@390); họ chữ 2->2. Không mục nào tăng.
  (/realtime@390 node 172->195 là dữ liệu live — docstring đã nói không tái tạo
  được qua thời gian; đó là lý do phải so trong cùng buổi.)
- Hover ba inner tab: 0 lỗi JS. Setup rules 1 readout, Detector rules 0 (đúng —
  pane per-bar của design không hover), Price context 2 crosshair + 1 readout.
- G3 ép nhánh own: data-xaxis="own", nhãn "trục riêng" hiện, crosshair 2->1,
  pane chuỗi KHÔNG bị dóng theo. Nhánh shared giữ nguyên 2.
- Sleeve không diagnostics (Swing, innerTabs=0): pill WAITING qua đúng fallback
  mvProgressChip :1884, 4 ô metadata, 0 lỗi. Số ô đổi 5/4/4 theo dữ liệu, không
  in placeholder (luật 9).
- 75 passed (skin + dom).

CHƯA ĐỌC: SECTION_ANATOMY.md vẫn chỉ tra lẻ (Today's Decision), chưa đọc đủ 11
section. Chưa commit.

════════════════════════════════════════════════════════════════════════════
ĐỌC HẾT SECTION_ANATOMY.md (480 dòng) — 2026-09-02
════════════════════════════════════════════════════════════════════════════
Bảng tra accent ở cuối file là hợp đồng đếm được: 10 section. Đo ra 8 đúng, 2 sai.

ĐÃ SỬA (next.css)
- Accent Track 1 Runtime: #5b9cf0 -> #e0913c. Accent Source Clocks: #9d8cf5 ->
  #5b9cf0. Cùng một cơ chế: skin-e cấp var(--d-exposure) cho MỌI heading, rồi
  `.journal-column h2::before` phủ tím lên TOÀN BỘ cột phải nên Source Clocks ăn
  theo Job journal. Sửa theo đúng khuôn skin-e đã dùng cho .orders-section.
  Sau sửa: 10/10 khớp.
- Header nháy: 3 dot -> 1. Anatomy: "chỉ dot Live nhấp nháy. Dot 'On schedule'
  tĩnh: nó là trạng thái, không phải nhịp tim." Rule skin-e nhắm
  `.runner-header-state i` nên bắt cả dot On schedule lẫn dot Scheduler, trong
  khi comment ngay trên nó viết "the live dot breathes" — số ít. Hệ quả của
  selector rộng, không phải báo động có chủ đích (dot Scheduler màu #798394 xám
  mờ). Dot Live nằm dưới .header-live-context nên vẫn thở.

ĐO ĐÚNG SPEC, KHÔNG PHẢI SỬA
- Now Monitor: 4 cell, 4 hue đúng bảng (#5b9cf0 · #9d8cf5 · #3a6ea8 · #6b5cb8),
  vạch bên TRÁI không phải trên, align baseline, MỘT dòng.
- Regime strip: flex-grow 20/11/3/1/9/16 — theo số ngày, không chia đều.
- Regime posterior: fill có sàn 0,40% đúng như anatomy.
- Today's Decision: tầng 1 repeat(5,1fr), tầng 2 repeat(3,1fr).
- Open Orders: 7 cột, Qty/Stop/ID căn phải, còn lại căn trái, không cột nào giữa.
- Job journal tab đang mở: #1c1a2b / #c9c0fb — tím cột phải, khác xanh nav.
- Source Clocks heading 15px, đúng chỗ anatomy nhấn "15px KHÔNG phải 17px".
- Paper equity: số 30px in "not measured", không in $0.

BA DƯƠNG TÍNH GIẢ TỰ BẮT ĐƯỢC — đừng lặp
1. "Mọi viền sai: 1px ra 0,8px, 2px ra 1,6px." Dựng một div mới với
   border-left:2px thì nó CŨNG ra 1,6px. devicePixelRatio 1,25 làm tròn về pixel
   thiết bị. Mọi số viền đọc từ trình duyệt này đều ×0,8 — của trình duyệt,
   không phải của trang. Không có viền nào sai.
2. "Now Monitor xếp 2 dòng." So `top` giữa hai con có cỡ chữ khác nhau dưới
   align-items:baseline thì luôn lệch. Kiểm bằng "có con nào nằm hẳn dưới đáy
   con khác không" -> không. Một dòng.
3. "Regime Monitor và Track 1 Market View mất accent (#000000)." Hai section này
   mang vạch ở node riêng chứ không ở ::before; #000000 là rgba(0,0,0,0) do sàng
   bỏ nhánh dò node. Đo lại đúng: cả hai khớp.

CÒN LẠI, KHÔNG SỬA — ghi để có người quyết
- Track 1 Runtime có 17 ô, design vẽ 8. Đây là NỘI DUNG, luật 10 nói repo đúng
  hơn về nội dung. Không đụng.
- Posterior chỉ 2 hàng (Calm 99,29% · Normal 0,71%), anatomy nói 4. Model đang
  n_states=3 trong khi CLAUDE.md ghi 4 — việc của backend, không phải CSS.
- Paper equity còn ba dấu "--" ở ba dòng phụ, màu #3ecf8e / #7194c2 / #7891ad.
  Câu "không in --" của anatomy nhắm số 30px, và số đó ĐÚNG. Ba dấu này rơi vào
  cùng cái khe giữa luật 1 và luật 2 như "+1" ở dải ba đồng hồ: không đủ xám để
  luật 1 tính, không phải tiền/lệnh để luật 2 tính.

NGHIỆM THU (cùng buổi, so với mốc đầu phiên)
- /realtime @1900 và @390: đè 0->0, cắt 0->0, tràn 0->0, cỡ chữ 12->12 và 11->11,
  họ chữ 2->2. Không mục nào tăng trên CẢ NĂM dashboard.
- 75 passed (skin + dom).
Chưa commit.

════════════════════════════════════════════════════════════════════════════
VÒNG 3 — so ảnh design với trang thật — 2026-09-02
════════════════════════════════════════════════════════════════════════════
ĐÃ SỬA
Cấu trúc (next.js + next.css)
- Bọc verdict + inner tabs + lưới lane vào MỘT card .mv2-shell (muc 3 "Card":
  viền #1e242c, radius 8, nền #0e1116). Verdict thành hàng đầu trong card: nền
  inset #0b0d11, padding 11px 15px, vạch đáy. Lưới lane bỏ khung riêng để không
  lồng card (luật 3).
- Ẩn hàng 7 chip #marketViewSummary: design không có, và cả 7 đã nằm trong hàng
  metadata ngay trên. Tooltip boundary_proof không mất (còn ở setup card :2963).
- Ẩn trục giờ .mv2-lane-axis (design chỉ đặt trục ở Price context) và
  #marketViewNote.
Nội dung (realtime.js)
- mvVerdict dựng HAI chip: COMPLETE (progress) + NO SIGNAL (status), thứ tự lấy
  theo đúng mvChips. Ô metadata thứ 5 đổi từ provenance sang "live session
  <date>". Trả lại cột phải muc 4.3: "<lane> failed N of M" + provenance.
- Hàng Slot decisions: value = tally "22 / 22", phụ đề = "aligned to slot times".
- Ô lane: width w*0.62 -> calc(w% - 2px). Đo được: ô 35,2px/khe 21,6px -> ô
  54,8px/khe 2px, tỉ lệ lấp 0,62 -> 0,965. Muc 4.5 dựng track bằng flex gap 2px.
- Declared chuyển vào CUỐI hàng legend (muc 4.5), dời nguyên node nên mỗi item
  còn data-tooltip + tabindex. Gỡ mvDeclaredConfig (0 tham chiếu sau khi dời).
- H của chart 320 -> 380 và 210 -> 250, đổi CẢ CSS lẫn viewBox nên sy vẫn = 1;
  đo lại dáng chữ trong svg = 1,000 (đổi mỗi CSS thì chữ bị kéo cao theo).
Hình (next.css)
- Lane: bỏ chấm trước tên; lane chặn mang HAI dấu hiệu theo muc 4.5 — nền hàng
  #100f12 VÀ vạch trái 3px #f2555a trên ô nhãn.
- Bỏ hai vạch DỌC trong lane (.mv2-lane-name/.mv2-lane-track border-right):
  muc 4.5 chỉ có vạch ngang.
- Tally "22/22 pass" căn giữa hàng: trước bị stretch rồi padding-top 11px đẩy lên
  đỉnh, trong khi .mv2-cell là absolute top:50%. Căn giữa nội dung, KHÔNG đổi
  align-items của grid vì ô nhãn phải cao đầy hàng cho vạch accent chạy suốt.
- Sleeve tab đang chọn #14251f/#8ae6cc; ghi chú session hổ phách -> #798394;
  legend nền inset + swatch 10x4 chữ nhật; readout lên head, màu #8dc0f7.
- Lề: #regimeStrip thiếu padding trong (chữ ở L=23 trong khi mọi hàng khác của
  .rg2-card ở L=41) -> 13px 18px theo anatomy hàng 4. Thân card Calm thiếu lề
  ngang (head có 12px 18px, thân 0) -> 18px. Trên tab Price context, .mv2-sc-head
  và hai .mv2-tabnote ở x=23 -> 41.

CÂU HỎI "vì sao candle là 09-01 mà slot series là 09-02" — CÓ ĐÁP ÁN
Không phải lỗi. `_sliced()` (track1_market_view.py:248) đọc kho parquet bar đã
lưu. Nếu ngày được hỏi KHÔNG có trong kho, nó lùi về `newest = max(days)` — phiên
gần nhất kho thật sự có — và trả kèm ngày đó cùng một note, cố ý "stated rather
than papered over". Slot thì do runner ghi live nên có 09-02 ngay từ 01:10 ET.
Đo: NKD_continuous_1m_8y.parquet mtime = 2026-09-02 11:47. Ảnh chụp TRƯỚC mốc đó,
khi kho mới tới 09-01. Sau 11:47 endpoint trả bars_session_date=2026-09-02 cho cả
ba sleeve, nbars=36/38/37, không còn bars_note. Tự lành khi job cập nhật bar chạy.

CHƯA QUYẾT — cần chủ dự án
- "2 vertical lines khi hover": đo ra ĐÚNG 1 đường mỗi pane, cùng x, readout bám
  đúng slot (1/22 → 7/22 → 17/22 → 22/22). Muc 4.7 ghi "crosshair trên MỌI pane",
  và readout nói "read both charts at the same minute". Muốn chỉ vẽ ở pane đang
  rê thì đó là đi ngược spec — chờ xác nhận, không tự bỏ.

HAI DƯƠNG TÍNH GIẢ TỰ BẮT
- "hover chết ở 50%/80% bề rộng": elementFromPoint trả về SECTION vì chart nằm
  ngoài khung nhìn. Cuộn vào rồi đo lại: chạy đúng ở mọi vị trí.
- "thân card Calm vẫn sát mép (L=23)": 23 là mép HỘP; rule padding 0 18px CÓ ăn,
  chữ nằm ở 41. Đo mép hộp thay vì đo chữ.

NGHIỆM THU: /realtime @1900 và @390 — đè 0->0, cắt 0->0, tràn 0->0, cỡ chữ 12->12
và 11->11, họ chữ 2->2. 75 passed. (/reports@390 cỡ chữ 8->12 KHÔNG phải hồi quy:
trang đó không nạp next.css, node 50->270 giữa hai lần chạy.) Chưa commit.

════════════════════════════════════════════════════════════════════════════
NẾN 09-01 DƯỚI SLOT 09-02 — tôi đóng sổ sớm, chủ dự án bác đúng — 2026-09-02
════════════════════════════════════════════════════════════════════════════
Tôi đã trả lời "không phải lỗi" sau khi đọc _sliced() và thấy fallback là có chủ
đích. Đó là trả lời "code làm gì", không phải "có ai thiết kế ra thế không".

ĐIỀU BỎ SÓT: repo ĐÃ tự giải quyết đúng câu hỏi này, ở nhánh khác của CÙNG file.
track1_market_view.py:1416 —
  "the store is appended after a session closes, so during a live session its
   newest bars are the previous day's. Same asymmetry the Normal-R4 branch
   settled — old numbers under a card labelled with today's session are worse
   than none."
Nhánh rule values theo luật "slot's OWN account first". Nhánh nến (_sliced) thì
chưa bao giờ được áp luật đó — nó vẫn thay bằng phiên hôm trước.

ĐÃ SỬA (realtime.js) — chỗ sai không cần tranh luận
Ghi chú G2 in "the crosshair matches within each pane, not across them", trong
khi hai pane VẪN chung trục: phép nhận span chỉ so SỐ SLOT, mà số slot thì bằng
nhau (22) dù ngày nào. Thêm điều kiện cùng phiên. Khi lệch ngày -> data-xspan
"own" -> data-xaxis "own" -> nhãn "trục riêng" hiện và crosshair thôi đồng bộ.
Luật 8 của hợp đồng thị giác.
Ghim: test_the_panes_refuse_one_axis_when_the_candles_are_a_different_session
+ test mốc ..._share_one_axis_when_they_are_the_same_session.
Mutation: gỡ điều kiện -> test "ngày khác" đỏ (shared thay vì own), test mốc vẫn
xanh; file khôi phục đúng hash c226bc52e51c. 77 passed.

MỘT LẦN FIXTURE SAI TỰ BẮT ĐƯỢC: bản đầu của test dựng bar 00:00–01:55 trong khi
slot chạy 01:10–02:55, nên chart giá chỉ vẽ 10 mark cho 22 slot và span bị từ
chối vì LỆCH SỐ ĐẾM. Test "ngày khác" khi đó xanh vì một lý do không liên quan
tới ngày. Sửa fixture cho nến phủ hết slot rồi mới đo lại.

CẦN CHỦ DỰ ÁN QUYẾT — hai vị trí trong repo mâu thuẫn nhau
- Docstring module: thà hiện phiên gần nhất còn hơn chart rỗng ("A chart of
  'today' would be empty on every normal day, which is a chart nobody trusts").
- Nhánh :1416: "old numbers under a card labelled with today's session are worse
  than none".
Bỏ hẳn fallback thì pane nến rỗng ~9 tiếng mỗi ngày (window NKD 01:10–02:55 ET,
parquet append đo được lúc 11:47). Tôi KHÔNG tự chọn.

"FILL CANDLE Ở SLOT ĐÃ CHẠY" — đo được cái gì có, cái gì không
- Bar hôm nay KHÔNG được lưu ở đâu cả. instrument_row() (track1_data_observation
  .py:77) NHẬN joined.frame — khung đã splice, có bar hôm nay — nhưng chỉ ghi mép
  (first/last/rows) rồi bỏ khung. Dashboard lại bị ràng buộc "opens no
  connection", nên nó không tự fetch được.
  => Muốn có NẾN đầy đủ (OHLC) theo từng slot thì phải sửa phía runner: ghi lại
  lát cắt window mà nó đã splice. Đó là code chạy live, tôi không tự đụng.
- NHƯNG close/volume theo từng slot thì ĐÃ CÓ: _slot_series(root, day, sleeve)
  đọc từ chính bản ghi của slot, và pane dưới đang vẽ nó. Hôm nay nó rỗng vì cả
  22 slot bị cổng regime chặn trước khi rule nào đọc số — không phải vì thiếu
  đường dữ liệu.

════════════════════════════════════════════════════════════════════════════
"NGÀY NÀO HIỆN NẾN NGÀY ĐÓ" — ba bước, 2026-09-03
════════════════════════════════════════════════════════════════════════════
Baseline trước khi làm: 05f339c (9 file). 21 file đã theo dõi của phiên/người
khác KHÔNG đưa vào — git status có 709 mục, chỉ 9 là của cuộc trò chuyện này.

BƯỚC 1 · runner giữ lại bar (global_index)
- track1_data_observation.py: thêm BARS_DIR, bars_path_for(), record_bars().
  Một file mỗi instrument mỗi phiên, GHI ĐÈ chứ không nối (22 slot không để lại
  22 bản). Ghi ra tên tạm rồi move vào chỗ, nên người đọc poll 8s không bao giờ
  mở phải bản nửa vời. KHÔNG BAO GIỜ ném lỗi.
- run_live_day_track1.py: gọi ngay sau instrument_row, trong vòng lặp đã có sẵn
  jf.frame. Bọc try/except RIÊNG dù caller đã bọc cả hàm: lỗi ở đây không được
  làm hụt obs.record phía dưới. Mất bức tranh là một giá; mất bằng chứng slot đã
  nhìn vào dữ liệu là giá khác hẳn.
- Mutation: gỡ lớp bọc riêng -> test "slot vẫn ghi bằng chứng khi ghi bar hỏng"
  đỏ với RuntimeError; khôi phục đúng hash 1f4bc06a2b9e.

BƯỚC 2 · dashboard đọc file đó (monitor/backend/track1_market_view.py)
- Tách _bars_for_day(): bar của ĐÚNG ngày được hỏi hoặc rỗng, không bao giờ ngày
  khác. Dùng chung cho cả hai nguồn.
- _sliced() nhận thêm root, hỏi hai nguồn theo thứ tự: khung của chính slot ->
  kho parquet ngày. BỎ HẲN việc lùi về phiên gần nhất.
- Đo trực tiếp: hỏi 09-02/09-01/08-25 trả đúng ngày đó 36 bar; hỏi 07-04 và
  2099-01-01 trả 0 bar, session_day=None, kèm lý do. Không lần nào trả ngày khác.
- Mutation: khôi phục việc thay ngày -> test đỏ; file về hash 7729943fd7d6.

BƯỚC 3 · trạng thái rỗng nói lý do (realtime.js)
- mvChartSvg: bỏ nhánh "Latest stored session <date>" — nó là code chết SAU khi
  hết thay ngày, và nó phát biểu một điều không còn xảy ra được nữa.
- mvPriceHead: dùng bars_note thay cho câu cứng "no bars for this window".
- test_dashboard_backend: test ghim tên mvDeclaredConfig đã sửa theo cấu trúc
  mới (mvDeclaredInline trong hàng legend), và ghim thêm rằng tooltip lý do còn
  nguyên — đó là thứ dễ mất nhất khi dời một khối.

CÒN LẠI: backend Flask đang chạy vẫn là code cũ (kiểm bằng endpoint: nó còn trả
"showing the most recent stored session"). Cần restart tiến trình đó mới thấy
trên trang. Tôi không tự tắt tiến trình của chủ dự án.

NGHIỆM THU: 309 passed (skin + dom + backend + session_bars). /realtime @1900 và
@390: đè 0->0, cắt 0->0, tràn 0->0, cỡ chữ 12->12 và 11->11, họ chữ 2->2.

── Bổ sung 2026-09-03: một lỗi của tôi, tìm ra khi kiểm "đã làm chưa" ──────────
Tôi nói file bar sẽ "vài KB". Đo thật: 28,3 MB, 2.052.686 dòng, trải từ 2018-01-02
— nguyên kho 8 năm, mỗi slot, mỗi công cụ. Khoảng 1,8 GB ghi đĩa mỗi cửa sổ phiên
để giữ ba tiếng bar. Nguyên nhân: tôi tưởng jf.frame là khung của phiên; nó là
lịch sử đã đông cộng nửa live nối vào.
Sửa: _around(frame, day) cắt còn ngày đó cộng một ngày mỗi bên. Lấy một ngày đệm
mỗi bên vì index mang đồng hồ của công cụ còn `day` là ngày phiên — lệch một ngày
giữa hai thứ đó sẽ cắt mất đúng phần cần giữ; ba ngày vẫn chỉ ~4 nghìn dòng.
Đo lại trên khung thật: 2.051.958 -> 1.067 dòng, 0,022 MB (nhỏ hơn 1.278 lần).
Mutation: gỡ lệnh cắt -> test đỏ; hash khôi phục 2c07b54620a3.
File 28 MB đã ghi ra trước đó: nén tại chỗ còn 0,041 MB, vẫn đủ 09-02 và 09-03.
Docstring đầu module còn mô tả hành vi thay-ngày đã bị gỡ -> viết lại.

ĐÃ CHẠY THẬT, qua server đang chạy:
  hỏi hôm nay 2026-09-03 -> 36 bar CỦA 09-03 (00:10->03:05). Kho parquet chưa có
  09-03 (append lúc 13:45 ET), nên số bar này đến từ khung của chính slot.
  hỏi 2026-07-04 -> 0 bar, bars_session_date=None, kèm lý do. Không thay ngày.
310 passed.

── Bổ sung 2: lệch 9 tiếng giữa hai nguồn bar — 2026-09-03 ────────────────────
Tìm ra khi trả lời "làm sao biết chart đúng". Phép tự kiểm: nến dựng từ khung của
slot, đường close dựng từ sổ ghi của slot — hai nguồn khác nhau, khớp thì tin được.
Chúng KHÔNG khớp: 0/13 điểm nằm trong biên độ nến, lệch tới 1.190 điểm.

Đào tới đáy, bỏ mọi giả định về đồng hồ: quét mọi độ lệch giờ rồi khớp theo GIÁ.
  lệch -9,0 giờ : 100,0% khớp trên 1.546 mốc
  mọi độ lệch khác : dưới 2%
Tokyo là UTC+9 => index của kho ngày là UTC KHÔNG múi giờ, còn khung slot mang
Asia/Tokyo. _bars_for_day quy chuẩn cái có múi giờ về spec["clock"] (Tokyo) và để
yên cái naive, nên hai nguồn bị cắt lệch nhau 9 tiếng. LỖI DO TÔI GÂY RA khi thêm
nguồn thứ hai — trước đó chỉ một nguồn nên không lộ.

Sửa ở CHỖ GHI (_as_store_clock): ghi ra tz-naive UTC, cùng quy ước với kho. Một
đáp án trên đĩa thay vì một quy tắc mọi người đọc phải nhớ.
Đo lại: 100,0% khớp trên 1.067 mốc chồng lấn (trước: 0,0%).
Mutation: gỡ chuẩn hoá -> test đỏ; khôi phục hash 1e42d4632589. 311 passed.

BA LẦN TÔI SUÝT KẾT LUẬN SAI TRÊN ĐƯỜNG NÀY
1. "lệch 1.190 điểm, không phải nhiễu" — vội. Ngày khác chỉ lệch ±205, đổi dấu.
2. "bar đang hình thành so với bar đã đóng" — nghe hợp lý, nhưng bar đang hình
   thành BUỘC phải nằm trong biên độ bar đóng; 0/13 thì không phải cơ chế đó.
3. "điều chỉnh hợp đồng liên tục" — nếu vậy chênh lệch phải là hằng số; std 320.
Chỉ phép quét không giả định (thử mọi độ lệch, khớp theo giá) mới ra đáp án.

── Đối chiếu IBKR + sửa thang volume — 2026-09-03 ─────────────────────────────
ĐỐI CHIẾU NGUỒN THỨ BA (chủ dự án yêu cầu)
Nối IB Gateway 4002, clientId=77 (tránh 1 runner / 89 bar provider / 90 safety /
99 backend / 10 broker). Không có runner nào đang chạy lúc nối. Lấy 2.026 dòng
MNKD qua chính đường fetch của hệ thống, ngắt trong finally.
Quét mọi độ lệch giờ, khớp theo giá:
  lệch -4,00 giờ : 100,0% khớp trên 36/36 nến
  các độ lệch khác: 5,6% trở xuống
Tháng 9 ET = UTC-4 => chart ở UTC, IBKR trả ET, GIÁ GIỐNG HỆT. Nến trên trang
đúng bằng thứ IBKR báo, không lệch một tick.

VOLUME CHỈ THẤY MỘT CỘT — nguyên nhân và bản sửa
Không phải thiếu dữ liệu: 36/36 nến có volume, 35 nến khác 0. Vấn đề là THANG.
MNKD ngày 09-03: đỉnh 110, trung vị 9 — gấp 12,2 lần. Chia theo đỉnh thì 19/35
cột có giao dịch cao dưới 4px trên pane 44px, tức vô hình; pane đọc thành một cột
và một vạch phẳng, mà vạch phẳng đó là phiên có giao dịch ở 35/36 phút.
Sửa: trần = phân vị 90 của các cột CÓ giao dịch (=32), cột vượt trần vẽ hết chiều
cao và đội một nắp mỏng để không lặng lẽ bằng trần. Sàn 1,5px cho cột có giao
dịch; cột bằng 0 GIỮ chiều cao 0 — phân biệt đó là lý do pane volume tồn tại.
Thêm nhãn trục phải "32 peak 110" / "0" (muc 4.7 cấp cột phải cho pane 2 và 5);
nhãn nói cả trần lẫn đỉnh thật, nếu không nó nói dối về thang.
Đo: cột trung vị 2,9px -> 10,1px; cột vô hình 19/35 -> 10/35 (10 cột còn lại là
volume 1-3, đúng 3% của trần nên sàn là trung thực); 3 cột chạm trần.
Mutation: quay lại chia theo đỉnh -> test đỏ ("cột trung vị chỉ 4,3px").
Kiểm khổ hẹp: 0 nhãn tràn khỏi svg ở cả 1605px lẫn 347px.

MỘT LẦN TEST ĐỎ VÌ HARNESS, KHÔNG PHẢI VÌ TRANG
wait_for_selector('.mv-vol') treo 20s: Playwright chờ phần tử NHÌN THẤY ĐƯỢC, mà
cột đầu tiên có volume 0 nên height="0" — vô hình. Chờ .mv-svg rồi đếm thì đúng.

@390: đè 0->3, cắt 0->3, cỡ chữ 11->13 — KHÔNG phải hồi quy. Node 172 -> 609:
lần chạy mốc chỉ dựng được một phần trang. Cả ba va chạm là nhãn dải chạy regime
("1d | Normal · 9d"...), không dính chart. Đúng ba va chạm đã ghi CHƯA GIẢI QUYẾT
từ đầu phiên, cùng một lý do. 313 passed.

── Bốn chỗ hỏng ở hover / dóng trục — 2026-09-03 ──────────────────────────────
1. HOVER KHÔNG HIỆN CHI TIẾT NẾN. Thật ra có: realtime.js đọc O/H/L/C vào .mv-tip.
   Nhưng .mv-tip là một DẢI rộng nguyên khung nằm DƯỚI plot — đo được top 742
   trong khi plot kết thúc ở 705. Người đang rê chuột trên cây nến được báo giá ở
   cách đó một chiều cao chart. Muc 4.7 gộp cả hai vào MỘT ô phía trên chart.
   Sửa: đưa O/H/L/C + volume vào .mv2-chart-readout (đọc theo PHÚT từ data-bars,
   không theo chỉ số); thêm volume vào data-bars; ẩn dải cũ, giữ node + listener.

2. HAI CHART KHÔNG DÓNG. Không phải luật ngày của tôi — hai pane cùng 09-03.
   Luật cũ đòi BẰNG SỐ SLOT: chart giá vẽ mọi slot của phiên (22), chuỗi chỉ mang
   slot có ghi số (20). Một buổi sáng bình thường là đủ để nó từ chối.
   Sửa: dóng theo PHÚT của slot. Mọi điểm phải tra được về một cột slot có thật;
   một điểm không tra được thì cả pane lùi về trục riêng, thay vì đặt một chấm
   vào chỗ nó không thuộc về. Kết quả: shared với 22 mark / 20 điểm.

3. HAI ĐƯỜNG DỌC, MỘT NÉT ĐỨT LỆCH TÂM. Hai bản cài: .mv-cross của realtime.js
   (chỉ pane giá) và .mv2-xhair của tầng next (mọi pane, đúng muc 4.7).
   Đường nét đứt lệch vì mvBindHover tính bằng lề 8/62 còn plot vẽ bằng 34/68 —
   đo được x=592,6 trên lưới tâm nến 341,9 bước 25,66, tức đứng giữa hai cây.
   Sửa: một hằng MV_PAD cho cả hai; ẩn .mv-cross. Sau sửa: lệch tâm nến 0,00 ở
   cả ba vị trí hover, còn đúng một đường mỗi pane.

4. TIẾNG VIỆT TRONG GIAO DIỆN TIẾNG ANH. "trục riêng — không dóng theo chart giá"
   là do tôi viết. -> "own axis — not aligned to the price chart".

BA LẦN PHÉP KIỂM CỦA TÔI KHÔNG KIỂM GÌ — bắt bằng mutation
- Test "đường kẻ đứng đúng tâm nến" vẫn XANH khi trả lề về 8/62: nó đo .mv2-xhair
  (lấy thẳng từ cx nên luôn đúng), không đo cái mang lỗi. Thêm assertion đọc
  .mv-tip -> CŨNG xanh, vì ở lưới 24 nến phép làm tròn nuốt sai số. Gỡ cả hai và
  thay bằng phép kiểm CẤU TRÚC ("chỉ một nơi khai lề"), có đỏ khi mutate.
  Lỗi lề giờ không còn hệ quả nhìn thấy được vì đường mang nó đã bị ẩn — nói
  thẳng vậy thay vì để một test trông như đang bảo vệ điều gì đó.
- Fixture đặt khoá `time_et` trong khi payload thật dùng `slot_time`. Luật cũ chỉ
  ĐẾM slot nên fixture sai tên vẫn qua. Luật mới đọc tên -> lộ ra.
- Một assertion còn ghim chuỗi tiếng Việt cũ.

@390 so với lần chạy đầy đủ trước đó: đè 3->3, cắt 3->3, cỡ chữ 13->13 — KHÔNG
tăng. 316 passed.

── Volume vẫn khó coi — vòng hai — 2026-09-03 ─────────────────────────────────
Vòng trước sửa THANG (trần theo phân vị 90). Lần này là ba thứ về HÌNH:

1. CỘT VOLUME ĐANG DÙNG ĐÚNG MÀU CỦA NẾN. Đo: #3ecf8e / #f2555a, y hệt thân nến.
   Muc 4.7 cho volume #1f6b4c / #7a2b30 kèm lý do: "tối hơn nến, vì volume là
   phụ". Không có rule .mv-vol nào nên nó ăn chung .mv-up/.mv-down với nến — một
   dải màu mạnh ngang chart giá, đặt ngay dưới nó, tranh mắt với thứ nó đi kèm.
2. PANE CAO 44px, spec 58px. Với công cụ mỏng, 14px thiếu là khác biệt giữa một
   cột và một vết. Sàn 1,5 -> 2px. Cột trung vị 10,1 -> 14,1px.
3. HAI LỖI HÌNH ĐO ĐƯỢC, không phải cảm giác:
   - nhãn "32 peak 110" ĐÈ nhãn giá "64127.80" — cả hai cùng đòi cột phải, mà
     plot giá kết thúc đúng chỗ pane volume bắt đầu. Dời xuống 20 đơn vị.
   - không có VẠCH ĐÁY: cột treo lơ lửng giữa hai pane, mắt không có gì để đọc
     chiều cao dựa vào. Thêm vạch #1a1f26.

ĐIỂM MÙ CỦA THƯỚC NGHIỆM THU — ghi lại để không tin nhầm
measure_dashboards.py báo "đè 0" ở 1900 NGAY CẢ KHI "32 peak 110" đang in chồng
lên "64127.80". Nó không nhìn vào bên trong SVG. Mọi chồng chữ trong chart phải
tự đo bằng getBoundingClientRect trên chính các <text>, không được dựa vào con số
0 của công cụ.

316 passed. @390 vẫn đúng 3 va chạm dải regime, không tăng.

── "vì sao bar có 2 lớp" — 2026-09-03 ────────────────────────────────────────
Là cái nắp tôi thêm ở vòng trước. Đo: đúng 3 nắp, mỗi nắp là thanh xám #a8b1c0
cao 1,6 nằm LƠ LỬNG cách đỉnh cột 0,9 đơn vị. Ý định là "cột này cao hơn khung",
nhưng vẽ tách rời khỏi cột thì mắt đọc thành hai thanh chồng nhau — và cả 3 trên
36 cột đều bị hỏi tới, tức tín hiệu sai 100% số lần nó xuất hiện.
Sửa: đổi thành KHE CẮT nằm bên trong đỉnh cột, tô màu nền card. Ký hiệu quy ước
cho "còn tiếp ngoài khung", và không thể nhầm là dữ liệu vì nó không THÊM gì —
nó lấy đi. Ghim: dấu phải nằm trong cột; mutation trả về vị trí lơ lửng -> đỏ.

── 3 va chạm @390: GIẢI QUYẾT XONG — 2026-09-03 ──────────────────────────────
Mục này tôi mang từ đầu phiên với nhãn CHƯA GIẢI QUYẾT. Giờ tái hiện ổn định nên
đo được, và ra ba việc khác nhau:

1. HAI trong ba là DƯƠNG TÍNH GIẢ CỦA THƯỚC. Đo dải chạy regime ở bề rộng 340px:
   số cặp có MỰC đè nhau = 3, số cặp có HỘP đè nhau = 0, và đúng 3 nhãn bị cắt
   (Calm·11d mực 60 trong hộp 53 · 1d: 12 trong 4,8 · Normal·9d: 66 trong 43,4).
   Chúng đè nhau bằng phần chữ đã bị overflow:hidden cắt bỏ và không ai vẽ ra.
   Luật cũ chỉ bỏ chữ nằm HOÀN TOÀN ngoài khung cắt — bỏ sót ca ở giữa.
   Sửa: GIAO hình chữ nhật với mọi khung cắt rồi so bằng phần giao; cắt theo từng
   trục vì overflow-y không cắt chiều ngang. Một luật bao trùm cả hai ca.
   Áp cho CẢ HAI thước: measure_dashboards.py và _VISIBLE_RECT trong suite skin.
   Kết quả: /realtime@390 đè 3 -> 0; bốn dashboard kia không đổi (0 -> 0).

2. "CẮT MÉP 3" thì là LỖI THẬT, và của tôi. Công cụ không nói phần tử nào nên con
   số đứng đó cả phiên mà không ai lần ra. Thêm clippedSample: ba phần tử đều là
   khối `declared` tôi dời vào hàng legend, vượt mép 193px, insideHiddenBox=True —
   không tràn ra ngoài trang, nhưng chữ bị cắt nên không đọc được.
   Sửa: cho nó flex-wrap + min-width:0, và ở <=680px bỏ margin-left:auto để nó
   chiếm trọn một dòng. muc 4.5 vốn cho hàng legend wrap; margin-left:auto của
   tôi là thứ đã ghim nó lại.

3. TỰ KIỂM CHO CHÍNH BỘ DÒ. test_no_text_sits_on_top_of_other_text luôn kỳ vọng 0
   nên tự nó không phân biệt "trang sạch" với "bộ dò hết dò". Thêm: dựng đúng một
   ca đè THẬT (hai dòng chữ ngoài mọi khung cắt) và đòi nó bị bắt, rồi dọn đi.
   Không có bước này thì việc tôi vừa nới luật lọc là việc không ai kiểm được.

SAU CÙNG: cả năm dashboard, cả hai khổ — đè 0, cắt 0, tràn 0. Lần đầu trong phiên.
Mốc DASHBOARD_BASELINE đã sinh lại bằng luật mới và commit cùng công cụ, đúng như
docstring của nó nói. 316 passed.

BỐN LẦN BẢN MÔ PHỎNG CỦA TÔI KHÁC CÔNG CỤ THẬT — đừng viết lại, hãy chạy nó
Tôi viết lại logic của thước trong trình duyệt để đo nhanh, và nó thiếu chốt
`el.contains(el)` mà công cụ thật có, nên ra 3 cặp "nhãn đè lên chính nó" —
getClientRects trả nhiều hình cho một text node. Ba lần trước cũng cùng dạng.

── "volume vẫn khó coi" — GỐC THẬT, tìm ra sau ba lần chữa triệu chứng ────────
Đo: .mv2-plot bị ghim height:320px + overflow:hidden, trong khi svg đã 420px sau
hai lần tôi nâng chart. Svg thò ra 101px, và ĐÚNG 101px cuối là pane volume —
cả 36 cột bị cắt đáy. Trên màn hình đọc thành "volume chỉ có một cột".
Ba lần chữa trước đều nhắm vào THANG, đều là triệu chứng:
  - trần phân vị 90  -> 110, 37, 33 vẽ bằng nhau, mất thứ tự
  - căn bậc hai      -> cột 110 chỉ cao gấp 3,4 lần trung vị thay vì 12
Sửa đúng chỗ: nâng khung lên 420 (giữ chiều cao CỐ ĐỊNH — realtime.css:1650 nói
rõ đó là chủ đích: phiên không có bar không được làm co panel), và cho svg BÁM
theo khung bằng `#marketViewChart .mv2-plot > .mv-svg { height:100% }` — phải nói
lại vì `#marketViewChart .mv-svg{height:320px}` (một id) thắng
`.mv2-plot > .mv-svg{height:100%}` (hai class). Chiều cao chỉ khai MỘT chỗ.
Rồi thang trả về TUYẾN TÍNH. Đo lại: tỉ lệ chiều cao đỉnh/trung vị = 12,2 đúng
bằng tỉ lệ giá trị 12,2; trục 110/55/0 (mốc giữa đúng nửa => tuyến tính);
0 cột bị cắt đáy; 0 giá trị vẽ giống nhau.
Ghim: test_the_plot_box_is_as_tall_as_the_chart_drawn_into_it — assert sy == 1 và
svg không thò ra khỏi khung. Thông điệp lỗi in luôn danh sách rule đang set
height, chính nhờ vậy mà lần này tìm ra thủ phạm trong một lượt chạy.

BÀI HỌC: "hai con số ở hai ngôn ngữ" lần thứ hai trong phiên (lần đầu là lề
hover 8/62 vs plot 34/68). Cả hai lần đều là một quyết định được chép làm hai
bản, và bản thứ hai trôi. Lần này bản CSS còn thắng cả bản JS.

317 passed. Cả năm dashboard, cả hai khổ: đè 0, cắt 0, tràn 0.

── Nến hiện giờ TƯƠNG LAI — lỗi múi giờ trên trục thời gian — 2026-09-03 ──────
Chủ dự án hỏi: Stress chưa chạy hết window sao nến và volume hiện đầy đủ?
Đo lúc 11:37 ET:
  MNQ : nến 09:35 -> 12:40 (hơn một tiếng ở TƯƠNG LAI), 13/24 slot đã chạy,
        latest_bar_et do slot ghi = 11:35 ET
  MES : 0 slot chạy, latest_bar_et = None, mà vẫn 12 nến 13:05 -> 14:00
Truy: kho MNQ KHÔNG có dòng nào của 09-03 (cuối 09-02 17:44) => nến đến từ file
phiên do runner ghi. File đó index naive tới 15:35; nếu là UTC thì = 11:35 ET,
đúng bằng latest_bar_et. Nhãn chart khớp nhãn naive 37/38.
=> CHART CẮT VÀ GHI NHÃN THEO UTC, trong khi mọi giờ khai trên trang là ET.
   MNQ đang hiện 09:35-12:40 UTC = 05:35-08:40 ET, tức bar TRƯỚC khi cửa sổ mở,
   rồi dán nhãn 09:35-12:40 lên. Đúng với cả ba sleeve, từ trước tới nay.

spec["clock"] KHÔNG phải đáp án: đó là đồng hồ giao dịch của rổ (Tokyo với rổ
Nhật), còn giờ context không nằm trên nó — 00:10-03:05 Tokyo không chứa nổi một
cửa sổ chạy 14:10-15:55 Tokyo. Chúng là ET, đúng như tên trường nói.

Sửa: quy index về ET trước khi cắt. Đo lại:
  MNKD 00:10 -> 02:55  (khớp latest_bar_et 15:55 JST = 02:55 ET)
  MNQ  09:35 -> 11:35  (dừng đúng bar mới nhất, hết nến tương lai)
  MES  0 nến           (cửa sổ 13:05-16:05 chưa mở — đúng điều chủ dự án chờ)
Kiểm chéo IBKR: trước khi sửa khớp 100% ở -4,00 giờ; sau khi sửa 97,1% ở 0,00
(một nến trên 34 lệch, là bar đang hình thành so với lúc kéo IBKR một tiếng trước).
Ghim: test_the_hours_on_the_chart_are_the_hours_the_window_is_declared_in.
Mutation: quay lại cắt theo spec["clock"] -> đỏ.

MỘT FIXTURE PHẢI SỬA THEO, và nó nói lên điều đáng nhớ: fixture cũ dựng index
NAIVE từ nhãn ET rồi ghi thẳng. Chỗ ghi quy về UTC, chỗ đọc quy về ET, nên một
index không khai múi giờ là một fixture không nói nó đang ở đồng hồ nào.

── Ba chỗ chủ dự án chỉ ra — 2026-09-03 ──────────────────────────────────────
1. CHẤM SLOT LỆCH SO VỚI Ô LANE. Đo: lệch tâm trung bình -31px, min -39,5.
   Gốc: HAI HÀNG DÙNG HAI LƯỚI. Lane 246px/1250,4/110; hàng slot 212/1268,4/126 —
   track lệch gốc 34px và rộng hơn 18px, nên chấm không thể trùng cột. Rule đặt
   lưới design chỉ nhắm `.mv2-lanes .mv2-lane`, mà hàng slot là ANH EM của
   .mv2-lanes chứ không nằm trong nó. muc 4.5 nói cả hai cùng một lưới.
   Cộng thêm: chấm đặt ở left = i*w + w*0.31, lệch sang trái một phần ba ô.
   Sửa: mở rộng selector lưới; chấm đặt ở tâm ô + translateX(-50%) nên đúng bất
   kể chấm to nhỏ. Đo lại: lệch tối đa 1,01px.

2. "ACROSS THE SESSION" CỦA STRESS KHÔNG HIỆN GÌ. Không phải thiếu pane: svg CÓ,
   nhưng 0 polyline, 0 chấm, và trục giá in "-∞" / "∞".
   Gốc: 18 điểm slot đều chỉ có slot_time, mọi số đọc là null — mà bộ lọc viết
   `Number.isFinite(Number(p.close))`. `Number(null)` là 0 và `isFinite(0)` là
   true, nên cả 18 điểm rỗng lọt qua như thể close = 0. Chart vẽ trên tập rỗng.
   ĐÚNG CÁI BẪY MÀ FILE NÀY TỰ CẢNH BÁO ở một chỗ khác, cách đó ba mươi dòng.
   Sửa: kiểm `p.close != null` TRƯỚC. Giờ hiện đúng câu cần hiện —
   "18 slots recorded, 0 carrying numbers — the line starts when the entry window
   opens and the detector has bars to walk." Đó chính là thông tin chủ dự án hỏi.
   Ghim + mutation: bỏ điều kiện null -> đỏ.

3. DETECTOR RULES DỒN CỤC. `detail` của gate viết cho dòng log, không cho trang:
   ba điều kiện nối bằng dấu chấm phẩy thành một câu chạy, dính luôn câu giải
   thích, và một số thô 0.004344608523355387 — mười tám chữ số.
   Sửa: tách theo chính dấu chấm phẩy người viết đã đặt, mỗi điều kiện một dòng;
   cắt thập phân còn bốn chữ số nhưng GIỮ giá trị đủ trong title — làm tròn cho
   mắt không được thành làm tròn bằng chứng.

MỘT PHÉP KIỂM SUÝT DỐI: test cho mục 2 lúc đầu đỏ ở CẢ HAI chiều, vì helper mở
tab chờ `.mv2-sc-svg` — đúng cái svg mà phép kiểm đòi KHÔNG được vẽ. Nó treo 20
giây rồi đỏ bất kể đúng sai. Chờ `.mv2-card` thay thế.

319 passed. Cả năm dashboard: đè 0, cắt 0, tràn 0.

── "stress đang chạy mà" — câu báo rỗng đổ lỗi sai chỗ — 2026-09-03 ──────────
Chủ dự án bác đúng: lúc 11:53 ET, cửa sổ Stress 10:35–12:30 ĐANG MỞ và 16/24 slot
đã chạy, mà pane vẫn bảo "the line starts when the entry window opens".
Đào: hai sleeve ghi HAI BỘ TỪ VỰNG khác nhau.
  NKD    : Close used · Trend filter (EMA 10) · ATR · Volume · Average volume
  Stress : Instruments below open and VWAP · Instruments gapped down ·
           Instruments with a wide range · Average basket gap
_SERIES_LABELS chỉ đi tìm bộ của NKD. Stress KHÔNG công bố giá — nó đo đếm rổ,
không đo giá — nên mọi tra cứu trượt và pane tưởng là "chưa có số".
Sửa câu: khi có slot đã ghi mà không slot nào có close, nói đúng điều đó và chỉ
sang tab Detector rules, thay vì bảo người đọc chờ một việc đã xảy ra rồi.
Ghim ý nghĩa chứ không ghim chuỗi: phải nêu SỐ slot đã ghi, và không được chứa
"entry window opens". Mutation: trả lại câu cũ -> đỏ.

CÒN MỞ, cần chủ dự án quyết: bốn số đo của Stress CÓ TỒN TẠI và có nghĩa, chỉ là
không phải giá. Vẽ chúng thành chuỗi riêng là thiết kế mới — muc 4.7 định nghĩa
pane này cho giá, và phần B nói design chưa từng vẽ price context của Stress.
Tôi không tự vẽ.

── Trùng lặp ở "No bar was evaluated" vs box Conditions — 2026-09-03 ─────────
Chủ dự án chỉ ra. Đo cả ba sleeve: box CONDITIONS LUÔN có mặt (NKD, Stress,
Swing đều coBoxConditions=true), và nó là TẬP CHA của phần tôi thêm:
  tôi thêm : 3 dòng — "Instruments below open and VWAP 2 (needs >= 4)" ...
  Conditions: 4 dòng — thêm dòng PASS, có nhãn PASS/FAIL, và định dạng đúng
              (+0.43% thay vì 0.0043)
Nên ba dòng ấy thừa ở MỌI trường hợp, và trình bày kém hơn bản đã có.

Đáng nói: bản GỐC cũng trùng — nó nhét cùng chuỗi đó vào giữa câu giải thích,
tức vừa trùng vừa dồn cục. Vòng trước tôi chỉ chữa phần "dồn cục" (tách dòng,
cắt thập phân) mà không hỏi "chỗ khác đã nói chưa". Sửa đúng là GỠ HẲN — vừa hết
trùng vừa hết dồn cục, và ít code hơn cả trước lúc tôi động vào.
Câu còn lại trỏ đúng hai chỗ có số: Setup rules (dừng ở đâu) và Conditions (số
nó dừng trên đó). Gỡ luôn mvConditionLines (0 tham chiếu) và CSS .mv2-cond-list.

BÀI HỌC: trước khi làm đẹp một khối chữ, hỏi "khối này có cần tồn tại không".
Tôi đã dành một vòng để trình bày lại thứ lẽ ra phải xoá.

319 passed.
