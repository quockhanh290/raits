# Futures Trust Audit — Hand-Off TODO

**Date:** 2026-07-05  
**Scope:** Classify futures decision-driving numbers. Identify which are verified vs unverified.
**Constraint:** Read-only hand-off. Do NOT touch futures code or re-run production fits.

---

## Root-Cause Rule

Every number that drives a go/no-go decision must have a committed script that reproduces it.
If no script exists, the number is unverified. The HMM_STABILITY_REPORT failure happened
because analysis was written without running it — commit the script first, then write the report.

---

## HMM_STABILITY_REPORT Contamination

`HMM_STABILITY_REPORT.md` contained four fabricated numbers (annotated in-place, see that file).
Any futures decision that cited or depended on this report needs recheck:

| Fabricated claim | Actual | Impact on futures |
|---|---|---|
| Annual agreement ≈98.5% | 67–68% | Weakens "weekly ≈ annual" equivalence argument |
| Quarterly churn 1.8% | ~1.1% | Direction unchanged (still low); re-freeze gate unaffected |
| 3/6 annual convergence fail | 6/6 converge | **Flips** convergence viability: annual IS viable per actual data |
| Covariance "full" | "diag" (production) | Report measured wrong model variant; numbers don't match production |

**Action:** Before trusting any futures conclusion that referenced the stability report,
re-run `raits/scripts/hmm_stability_measure.py` and `raits/scripts/hmm_annual_convergence.py`
against the current `PRODUCTION.pkl` to get authoritative replacements.

---

## Decision-Driving Numbers — Classification

### 1. fit_C Paper Baseline

| Item | Value | Source script committed? | Status |
|---|---|---|---|
| fit_C net P&L (2017–2024) | $52,962 | `global_index/verify_runner_real.py` (untracked→now tracked) | ✅ script committed in this session |
| fit_C Calmar ratio | 2.75 | same | ✅ |
| fit_A degradation floor | Calmar 2.38 | unclear — check `global_index/verify_runner_real.py` output | ⚠️ verify script produces this number |

**Action:** Run `global_index/verify_runner_real.py` and confirm it reproduces $52,962 / 2.75.
If it does not, the baseline is unverified.

---

### 2. Annual Re-Freeze Gate (<5% label change)

| Item | Value | Source | Status |
|---|---|---|---|
| Gate threshold | <5% label churn triggers block on promotion | derived from HMM_STABILITY_REPORT | ⚠️ NEEDS RECHECK |

The <5% threshold was set when the report claimed ~1.8% quarterly churn. Actual is ~1.1%.
Direction is unchanged (both are well below 5%) — gate is conservative in the right direction.
BUT the agreement number (98.5% → 67–68%) weakens the equivalence claim the gate was built on.

**Action:** Re-run `hmm_stability_measure.py`. If label agreement on valid days is truly 67–68%
(not 98.5%), reconsider whether the weekly-expanding → annual re-freeze promotion is safe
for the futures path. The equity path vault-test baseline assumes weekly-expanding; any futures
path that switches to annual needs a separate OOS validation.

---

### 3. Sensitivity Gates (fit_A→fit_C, fit_B→fit_C)

| Item | Value | Source script committed? | Status |
|---|---|---|---|
| fit_A→fit_C sensitivity gate | unknown | check `raits/scripts/hmm_sensitivity_gate.py` | ⚠️ verify |
| fit_B→fit_C sensitivity gate | unknown | same | ⚠️ verify |

**Action:** `hmm_sensitivity_gate.py` is committed (commit `5cc8dbf`). Run it and confirm it
produces the gate thresholds used in the production promotion checklist. If thresholds were
set by eyeballing report tables rather than script output, they are unverified.

---

### 4. NKD (Nikkei Futures) Numbers

| Item | Status |
|---|---|
| Any NKD P&L / Sharpe claims | ⚠️ unknown provenance — audit before citing |

**Action:** Locate the script that produced NKD figures. If no script exists, the numbers
are unverified. Do not cite in any go/no-go memo without a reproducing script.

---

### 5. STRESS_MID Borderline Decision (p=0.112)

| Item | Value | Source | Status |
|---|---|---|---|
| STRESS_MID inclusion p-value | 0.112 | `bootstrap_strategy.py` (committed `a28e729`) | ✅ script exists |
| Decision | defer/borderline | system analysis snapshot | ✅ documented |

This number is verified — `bootstrap_strategy.py` is committed and the decision to defer
is recorded in `project_system_analysis` memory. No action needed.

---

### 6. Reconcile Chain (fit_A → fit_B → fit_C promotion)

| Step | Script | Status |
|---|---|---|
| fit_C baseline production run | `global_index/verify_runner_real.py` | ✅ committed this session |
| HMM stability gate | `raits/scripts/hmm_stability_measure.py` | ✅ committed `98363b5` |
| Annual convergence check | `raits/scripts/hmm_annual_convergence.py` | ✅ committed `a28e729` |
| Sensitivity gate | `raits/scripts/hmm_sensitivity_gate.py` | ✅ committed `5cc8dbf` |
| OOS vault test (equity) | `configs/wfo_report.json` | ✅ sealed in `final_params.yaml` |
| OOS vault test (futures) | **NONE** | ❌ NO futures OOS vault run exists |

**Critical gap:** The futures path has no sealed OOS test equivalent to the equity vault test.
The fit_C baseline is IS performance (2017–2024 includes the training period).
Before futures go-live, an equivalent OOS period (2023–2024 held out) must be run and sealed.

---

## Summary Action List

1. **Run `hmm_stability_measure.py`** → replace fabricated 98.5% / 1.8% with actual numbers
2. **Run `hmm_annual_convergence.py`** → confirm 6/6 convergence finding
3. **Run `global_index/verify_runner_real.py`** → confirm $52,962 / Calmar 2.75 baseline reproduces
4. **Audit NKD figures** → find or commit the producing script; mark unverified until then
5. **Define futures OOS vault test** → hold out 2023–2024, run, seal before live consideration
6. **Reconsider weekly→annual equivalence** → 67–68% agreement (not 98.5%) needs fresh analysis
   before switching futures HMM cadence from weekly-expanding to annual re-freeze

---

## What NOT to Do

- Do not re-run or reseal the equity vault test (`configs/final_params.yaml` is locked)
- Do not modify `engine.py` / `decision_unit.py` — the equity path is sealed
- Do not treat the fit_C IS baseline as an OOS result
- Do not promote a new HMM fit to `PRODUCTION.pkl` without passing all four gate scripts
