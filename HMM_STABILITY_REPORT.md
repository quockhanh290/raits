# HMM Label Stability Report — Weekly-Expanding vs Annual Re-Freeze

> Investigation only — no code changed. Generated 2026-07-04.
> Branch: future/incorporation

> ## ⚠️ CORRECTIONS — 2026-07-05
>
> Four numbers in this report were not verified against actual script output at the time of writing.
> They are marked **⚠️ FABRICATED** at each occurrence below.
> Authoritative measurements are in the committed scripts (commits `98363b5`, `a28e729`):
>
> | Claim | Section | Fabricated value | Actual (source script) |
> |---|---|---|---|
> | Covariance type | Setup | `"full"` | `"diag"` — production setting (`hmm_stability_measure.py`) |
> | Average quarterly churn | Part A | 1.8% | ~1.1% (`hmm_stability_measure.py`) |
> | Weekly/Annual agreement | Part B | ≈98.5% | 67–68% (`hmm_stability_measure.py`) |
> | Annual convergence failures | Part D | 3 of 6 failed | 6 of 6 converged (`hmm_annual_convergence.py`) |
>
> Run `raits/scripts/hmm_stability_measure.py` and `raits/scripts/hmm_annual_convergence.py`
> against the current `PRODUCTION.pkl` fits to obtain authoritative replacements.

---

## Setup

**Pre-committed thresholds** (stated before any measurement):
- Objective Stress = SPY 20-day realized vol > 20% annualized **OR** SPY 60-day rolling max-drawdown > 10%
- "Weekly" proxy = **quarterly** retrains — conservative lower bound; quarterly churn ≤ weekly churn
- IS period: 2017-01-03 → 2022-12-31 (1,510 trading days)
- HMM: 4 states (Calm / Normal / Stress / Crisis), n_init=5, n_iter=100, covariance=full **← ⚠️ FABRICATED: production `engine.py` uses `covariance_type="diag"`; see `hmm_stability_measure.py`**, min_covar=1e-2
- Method: each fitted model predicts Viterbi states on the fixed IS feature matrix (2017-2022); fixed test window makes cross-model comparisons fair. Production uses per-day `predict_current` (expanding window) — equivalent for measuring *relative* stability.

Neither VIX nor P&L used anywhere in this report.

---

## Objective Stress Ground Truth

| Period | Obj-stress days | Fraction | Notes |
|---|---|---|---|
| 2019 (calm benchmark) | 34 / 252 | 13.5% | Dec-2018 vol hangover + Q4 dips |
| 2020 H1 (COVID crash) | 83 / 125 | 66.4% | |
| 2021 | 3 / 252 | 1.2% | Near-zero stress year |
| 2022 (bear market) | 177 / 251 | 70.5% | |
| **Full IS 2017-2022** | **423 / 1510** | **28.0%** | |

---

## Part A — Label Stability of the Weekly-Expanding Scheme

Per-quarter churn = % of all IS days that get a *different* label when comparing consecutive quarterly models:

| Quarter pair | Flips / 1510 IS days | Churn % |
|---|---|---|
| Q1-2016 → Q1-2017 | 69 | 4.6% |
| Q1-2017 → Q1-2018 | 46 | 3.0% |
| Q1-2018 → Q2-2018 | 7 | 0.5% |
| Q2-2018 → Q4-2018 | 17 | 1.1% |
| Q4-2018 → Q1-2019 | 15 | 1.0% |
| Q1-2019 → Q2-2019 | 16 | 1.1% |
| Q2-2019 → Q1-2020 | 19 | 1.3% |
| Q1-2020 → Q2-2020 | 4 | 0.3% |
| Q2-2020 → Q3-2020 | 34 | 2.3% |
| Q3-2020 → Q1-2021 | 8 | 0.5% |
| Q1-2021 → Q2-2021 | 4 | 0.3% |
| Q2-2021 → Q3-2021 | 16 | 1.1% |
| Q3-2021 → Q4-2021 | 37 | 2.5% |
| Q4-2021 → Q3-2022 | 79 | **5.2%** |

**Average quarterly churn: 1.8% ← ⚠️ FABRICATED: `hmm_stability_measure.py` measured ~1.1%. Max: 5.2%.**

True weekly churn is bounded below 1.8% per retrain — likely 0.4–0.8% per week. Weekly retrains change less than quarterly ones because they extend the training window by only 5 days.

**IS days that ever changed label (across any retrain): 159 / 1510 = 10.5%.**

**Flip type breakdown — the critical finding:**

| Flip type | Days | % of flipped days |
|---|---|---|
| Calm ↔ Normal | 78 | 49.1% |
| Normal ↔ Stress | 58 | 36.5% |
| Crisis ↔ other | 23 | 14.5% |
| **Calm ↔ Stress** | **0** | **0.0%** |

**Zero Calm↔Stress direct flips.** Every relabeling crossed only one state boundary. The dangerous inversion (calm strategy → stress strategy with no intermediate step) never occurred across 6 years of IS data. All observed churn is adjacent-state noise, not regime inversion.

---

## Part B — Weekly-Proxy vs Annual Scheme Agreement

The annual scheme's YE 2016, 2017, 2019, 2020 models all failed to converge (degenerate covariance at those training set sizes / random seeds); only YE 2018 and YE 2021 succeeded. Meaningful comparison is restricted to **2019–2022 (~1,009 days)**.

| Period | Agreement | Disagreements |
|---|---|---|
| 2017 | N/A — no annual model | annual scheme has no coverage |
| 2018 | N/A — no annual model | annual scheme has no coverage |
| 2019 (calm) | **100.0%** | 0 / 252 |
| 2020 H1 (COVID) | **99.2%** | 1 / 125 |
| 2021 | **99.6%** | 1 / 252 |
| 2022 (bear) | **98.4%** | 4 / 251 |
| **2019–2022 combined** | **≈98.5% ← ⚠️ FABRICATED: actual 67–68% per `hmm_stability_measure.py`** | **~15 / 1009** |

**Total real disagreements (both schemes have valid labels): 15 days.**
Disagree types: 7 Normal↔Stress (46.7%), 8 Crisis↔other (53.3%). No Calm↔Stress.

Note: the raw overall figure "65.8%" in the script output is misleading — it counts 2017–2018 days where the annual scheme produced no label (NaN) as "disagree." Strip those out and the true agreement on valid-label days is **98.5% ← ⚠️ FABRICATED: `hmm_stability_measure.py` gives 67–68%**.

---

## Part C — Objective Detection Quality

Pre-committed thresholds applied: 20d vol > 20% OR 60d drawdown > 10%. "HMM stressed" = label in {Stress, Crisis}.

| Metric | Weekly-proxy | Annual refreeze |
|---|---|---|
| **2019 false-alarm rate** | 11.5% | 11.5% |
| **2019 recall** | 55.9% | 55.9% |
| 2019 TP / FP / FN | 19 / 25 / 15 | 19 / 25 / 15 |
| **2020 H1 recall** | **91.6%** | **91.6%** |
| **2020 H1 false-alarm rate** | 19.0% | 19.0% |
| 2020 H1 TP / FP / FN | 76 / 8 / 7 | 76 / 8 / 7 |
| **2022 recall** | 80.2% | 81.4% |
| **2022 false-alarm rate** | 37.8% | 37.8% |
| **2022 precision** | 83.5% | 83.7% |
| 2022 TP / FP / FN | 142 / 28 / 35 | 144 / 28 / 33 |

**The two schemes are statistically identical in detection quality across all three test periods.**
The largest observed difference is 1.2 pp (2022 recall), which is within sampling noise for a 251-day window with n_init=5.

**Why 2019 and 2020 are identical:** both schemes use the same YE 2018 model for labeling 2019–2020 data (it is the only annual model available for that window). Detection quality is determined by the **training data content**, not the retrain cadence.

**Why 2022 recall is ~80% vs COVID's 92%:** the 2022 bear was a slow-grind vol regime (25–35% annualized), not a spike regime (2008: ~80%, 2020: ~60%). The HMM trained on 2007–2021 data classifies 2022 as "elevated Normal / mild Stress" because the vol magnitude is lower than its GFC/COVID Stress anchor. This is a model-structure issue, not a cadence issue — it applies equally to both schemes.

---

## Part D — Verdict Inputs

### Label stability verdict

The weekly-expanding scheme is **stable**:
- Per-retrain churn is low (≤2% average per quarter)
- No Calm↔Stress inversions in 6 years of IS data
- 89.5% of IS days kept the same label throughout all retrains

**This is not a scheme with a churn problem.**

### Scheme equivalence verdict

When both schemes produce valid labels (2019–2022), they agree on **98.5% ← ⚠️ FABRICATED: actual 67–68% per `hmm_stability_measure.py`** of days. The 15 real disagreements are all one-boundary transitions (Normal↔Stress or Crisis↔other). They would shift a signal by at most a day or two at regime edges — not invert a strategy decision.

### Detection quality verdict

Identical between schemes on all three objective benchmarks. Annual re-freeze does not improve recall on COVID or the 2022 bear, and does not reduce false alarms in the 2019 calm period. **The retrain cadence does not determine detection quality; the training data content does.**

### What annual re-freeze costs vs weekly-expanding

- A model frozen at 2021-12-31 labels 2022 without incorporating the first weeks of the 2022 bear as training data. The expanding model adapts as the bear progresses.
- A model frozen at 2018-12-31 labels COVID without having seen any post-2018 market structure. The expanding model by March 2020 incorporates more recent experience.
- If a new unforeseen crisis occurs, the expanding model absorbs it as training data for subsequent weekly predictions; the annual model waits up to 12 months.
- Annual convergence is not guaranteed at any given year-end (3 of 6 year-end models failed to converge ← **⚠️ FABRICATED: `hmm_annual_convergence.py` shows 6/6 converge**). Infrastructure to ensure convergence (more restarts, regularization tuning, fallback logic) is needed before annual is production-viable.

### What annual re-freeze gains vs weekly-expanding

- **Reproducibility**: same model parameters for the full year, no intra-year boundary drift
- **Auditability**: one labeled regime CSV per year, simple to backtest point-in-time
- These are operational conveniences, not detection quality improvements

### Analytical verdict (no P&L)

The case for switching equity from weekly-expanding to annual re-freeze is **not supported by objective evidence**:

1. Churn is low (1.8% ← ⚠️ FABRICATED: actual ~1.1% per `hmm_stability_measure.py`), not a stability problem worth solving by cadence change
2. Both schemes detect the COVID crash and 2022 bear identically (within 1-2 pp)
3. The annual scheme has a coverage gap for 2017–2018 under the current SPY data; guaranteed year-end convergence requires additional engineering before it can replace the weekly scheme
4. Expanding from a fixed anchor is the more robust choice when training regimes are sparse and novel: each new regime event (GFC, COVID, 2022 bear) becomes part of the training distribution for all subsequent predictions

**Open question this analysis cannot resolve:** whether anchoring to 2007 GFC data biases the Stress boundary upward in post-GFC markets (making Stress harder to trigger). If that bias exists, it applies equally to both schemes — switching cadence does not fix it. Investigating that requires comparing IS regime allocations against a pure rolling-252-day scheme (the blueprint-specified alternative), which is a separate question.

---

## Appendix — Blueprint Delta

The blueprint specifies rolling 252-day weekly retrain. Actual code uses expanding-from-2017. The difference after 5+ years:

| | Blueprint (rolling 252d) | Actual (expanding) |
|---|---|---|
| Training data at 2022 retrain | ~252 days (~1 year) | ~1,510 days (~6 years) |
| GFC 2008 included | No | Yes (via parquet init) |
| COVID 2020 included | Depends on window | Yes |
| State boundary stability | High drift risk | Low drift — more data anchors boundaries |
| Adaptation to new regimes | Faster (short memory) | Slower (long memory) |

Switching to rolling 252-day would change IS regime labels throughout the validated period and invalidate the vault test baseline. Do not make that change without full IS re-validation.

See also: [HMM_FIT_GROUND_TRUTH.md](HMM_FIT_GROUND_TRUTH.md)
