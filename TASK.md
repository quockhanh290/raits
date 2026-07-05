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

### Completed (run_smoke_test — viết xong, chưa run)
- [ ] global_index/run_smoke_test.py — cold-start integration smoke test; pending first run

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

### Next steps

**KHI IBKR ACCOUNT MỞ:**
- [ ] 1. Data: xác nhận NKD trong CME bundle + subscribe + permission + Rule 576 cert
- [ ] 2. IBKRBroker: fetch_bars + send_order (ib_async, Gateway 7497) + format adapter
- [ ] 3. runner.dump_state(): điền Group B (slippage, fill quality, paper-vs-backtest, health, timing)
- [ ] 4. Dashboard live mode: poll live_state.json
- [ ] 5. Reconcile IBKRBroker fill khớp assumption deploy_sim (khi có fill thật)

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
