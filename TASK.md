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

### PENDING (Option C — user must run)
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
- [ ] STRESS_MID Phase C2: add 10:20 ET morning cron with stress_bars_1015 populated

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

### Next steps
- [ ] **Bracket order** (khảo sát xong, chưa làm) — xem Key decisions.
- [ ] Verify live phiên kế: log phải có `place_stop: accepted ... status=PreSubmitted`
      (và dòng `stop X → Y (tick Z)` nếu có nắn); `check_open_orders.py` exit 0.

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
03df38c fix(stp): a failed cancel names the clientId that can actually do it
6a39c58 fix(stp): round stop prices to the tick grid — the actual cause of the naked positions
eb5309f feat(stp): repair tool, and fix instrument-name lookup for NKD stops
80d2bae test(stp): replace an acceptance criterion that could never fail
c40b136 fix(stp): detect naked positions from broker truth, not from a local field
fdfad29 fix(stp): place_stop confirms IBKR accepted the order instead of its own id
```

---

## Sub-task: Slot NKD đêm không chạy — ROOT CAUSE xác định (2026-08-06)
Status: ĐIỀU TRA XONG — CHƯA VÁ

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

### Next steps — ba việc, CHƯA LÀM, chờ quyết định

**(b) Nửa môi trường — BẮT BUỘC, làm trước, rẻ nhất**
- [ ] Đặt máy không ngủ khi chạy pin: `powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0`
      rồi `powercfg /setactive SCHEME_CURRENT`. Hiện DC = 0x258 (600s), AC = 0 (không bao giờ).
- [ ] Kiểm tra lại: `powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE`
- ⚠️ Không bản vá code nào chạy được job khi máy đang ngủ. Phiên ngủ 23:20–00:03 trùng cửa sổ
      đêm → mất 8 slot bất kể vá gì. Đây là máy cá nhân nên là quyết định của user, không tự đổi.

**(a) Nửa code — biến "im lặng 10 tiếng" thành "trễ vài phút, có log"**
- [ ] Heartbeat job trong `make_scheduler()`: cron mỗi 1–5 phút, chỉ `log.debug`. Mục đích duy
      nhất là chặn trần `wait_seconds` của `BlockingScheduler._main_loop`, để sau khi máy thức
      scheduler đánh giá lại trong vài phút thay vì vài giờ.
- [ ] `misfire_grace_time` cho slot NKD đêm: đủ cho trễ vài phút vẫn chạy
      (`diff_desired_vs_held` idempotent — xem docstring `_live_day_body`), nhưng KHÔNG cho slot
      trễ hàng giờ chạy khi cửa sổ đã đóng. Mặc định APScheduler = 1s → hiện đang bỏ hẳn.
- [ ] Cảnh báo khi phát hiện trượt: nếu `now - scheduled_time > ngưỡng`, log WARNING kèm số giây.
      Không có cái này thì lần sau vẫn không ai biết.
- [ ] Test + gate reconcile như thường lệ (sửa `run_scheduler.py`, không đụng runner/engine).

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
