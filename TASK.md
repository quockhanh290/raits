## Task: RAITS — IS Optimization → WFO → OOS Preparation
Status: IN PROGRESS

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

### In progress
(none — pick next from Next steps)

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
