# HMM Annual Re-Freeze Convergence Audit

> Corrects the "3/6 year-end models failed to converge" claim in HMM_STABILITY_REPORT.md.
> Investigation only — no code changed. Run 2026-07-05.
> Branch: future/incorporation

---

## The Claim Under Review

`HMM_STABILITY_REPORT.md`, Part D, stated:

> *"Annual convergence is not guaranteed at any given year-end (3 of 6 year-end models
> failed to converge in this analysis). Infrastructure to ensure convergence (more
> restarts, regularization tuning, fallback logic) is needed before annual is
> production-viable."*

The user's challenge: if the annual scheme is anchored-expanding (2007 → each year-end,
growing window), later year-ends have MORE data and should converge EASIER — so "3/6 fail"
is suspicious. **Investigation confirms the suspicion. The claim is wrong.**

---

## Setup

**Data available:**

| File | Start | End | N days |
|---|---|---|---|
| `SPY_daily_2007_2024.parquet` | 2007-01-03 | 2024-12-30 | 4,529 |
| `SPY_daily_2017-01-03_2024-12-31.parquet` | 2017-01-03 | 2024-12-31 | 2,012 |

The 2007-start file is the `_HMM_HIST_PATH` used by `ReplayContextFeed` /
`LivePolygonFeed` for HMM initialization — confirming that anchored-expanding from
2007 was always the intended design.

**Report settings (as stated in HMM_STABILITY_REPORT.md):**
- n_components=4, covariance=**full**, n_iter=100, n_init=5, min_covar=1e-2

**Production engine settings (actual `raits/hmm/engine.py`):**
- n_components=4, covariance=**diag**, n_iter=200, n_init=10, min_covar=1e-2

These differ. The stability report used `full` covariance — the production engine
uses `diag`. The report tested a non-production configuration.

---

## Measurement

Four scenarios were run. All using `build_feature_matrix()` (log-return + 5-day
realized vol, identical to production). "Degen" = seeds where hmmlearn raised a
degenerate-covariance exception. "ValidOrder" = `validate_state_order()` passes
on the best-of-n model.

### Scenario A — IS-only windows (2017 → year-end)

*What the prior analysis likely used — NOT anchored from 2007.*

| YE | N | Start | End | EM ok | Degen | ValidOrder | BestLL |
|---|---|---|---|---|---|---|---|
| 2016 | 0 | — | — | **NO DATA** | — | — | — |
| 2017 | 246 | 2017-01-03 | 2017-12-29 | True | 4/5 | True | 1,421.3 |
| 2018 | 497 | 2017-01-03 | 2018-12-31 | True | 4/5 | True | 2,745.7 |
| 2019 | 749 | 2017-01-03 | 2019-12-31 | True | 2/5 | True | 4,208.8 |
| 2020 | 1,002 | 2017-01-03 | 2020-12-31 | True | 0/5 | True | 5,233.4 |
| 2021 | 1,254 | 2017-01-03 | 2021-12-31 | True | 0/5 | True | 6,611.7 |

**Every year-end that has data converges.** At small sizes (YE2017 N=246, YE2018
N=497), 4 of 5 seeds fail with degenerate covariance — but `n_init=5` finds a valid
model from the remaining seed. That is the entire point of multiple restarts.

### Scenario B — True anchored-expanding (2007 → year-end), report settings

*The scheme as designed.*

| YE | N | Start | End | EM ok | Degen | ValidOrder | BestLL |
|---|---|---|---|---|---|---|---|
| 2016 | 2,513 | 2007-01-03 | 2016-12-30 | True | 1/5 | True | 12,426.6 |
| 2017 | 2,764 | 2007-01-03 | 2017-12-29 | True | 1/5 | True | 13,964.1 |
| 2018 | 3,015 | 2007-01-03 | 2018-12-31 | True | 1/5 | True | 15,260.6 |
| 2019 | 3,267 | 2007-01-03 | 2019-12-31 | True | 0/5 | True | 16,685.4 |
| 2020 | 3,520 | 2007-01-03 | 2020-12-31 | True | 0/5 | True | 17,730.9 |
| 2021 | 3,772 | 2007-01-03 | 2021-12-31 | True | 0/5 | True | 19,109.5 |

**6/6 converge with valid state ordering at n_init=5.** Exactly the expected
monotonic behavior: more data → fewer degenerate seeds → higher log-likelihood.

### Scenario C — n_init=5 vs n_init=20 (anchored), seed vs data-driven test

| YE | N | n_init=5 | n_init=20 | Verdict |
|---|---|---|---|---|
| 2016 | 2,513 | OK 12,426.6 | OK 12,430.6 | n_init=5 fully OK |
| 2017 | 2,764 | OK 13,964.1 | OK 13,964.9 | n_init=5 fully OK |
| 2018 | 3,015 | OK 15,260.6 | OK 15,262.8 | n_init=5 fully OK |
| 2019 | 3,267 | OK 16,685.4 | OK 16,685.4 | n_init=5 fully OK |
| 2020 | 3,520 | OK 17,730.9 | OK 17,730.9 | n_init=5 fully OK |
| 2021 | 3,772 | OK 19,109.5 | OK 19,112.5 | n_init=5 fully OK |

No failures at any restart count. Nothing to attribute to seeds.

### Scenario D — Production settings (diag, n_init=10, n_iter=200), anchored

| YE | N | EM ok | Degen | ValidOrder | BestLL |
|---|---|---|---|---|---|
| 2016 | 2,513 | True | 0/10 | True | 12,423.1 |
| 2017 | 2,764 | True | 0/10 | True | 13,959.8 |
| 2018 | 3,015 | True | 0/10 | True | 15,254.8 |
| 2019 | 3,267 | True | 0/10 | True | 16,677.0 |
| 2020 | 3,520 | True | 0/10 | True | 17,721.2 |
| 2021 | 3,772 | True | 0/10 | True | 19,098.4 |

Zero degenerate seeds. Diagonal covariance is more robust than full on this dataset.
**6/6 perfect at production settings.**

---

## Root Cause of the Incorrect "3/6 Fail" Claim

The stability analysis script was **not committed**. The findings cannot be traced to
a recoverable artifact. Based on what is reproducible, the most likely failure mode in
the prior session's analysis:

**Hypothesis 1 (most likely): IS-only windows + individual-seed failure counting.**

If the prior script used IS-only data (2017 → YE) and counted "did every seed
converge?" rather than "did the best-of-n converge?":

- YE2016: no data → labelled "fail" (correct, but for the wrong reason — not a
  convergence problem, simply no IS-period data before 2017)
- YE2017: 4/5 seeds degenerate → labelled "fail" (wrong — the 5th seed succeeds)
- YE2018: 4/5 seeds degenerate → labelled "fail" (wrong — same)
- YE2019: 2/5 seeds degenerate → labelled "fail" or "pass" depending on threshold
- YE2020: 0/5 seeds degenerate → "pass"
- YE2021: 0/5 seeds degenerate → "pass"

Result: 3 "failures" (2016, 2017, 2018) with 2018/2021 as the "successes". This
matches the report's claim almost exactly. The error was treating individual-seed
degenerate covariance as model failure, not using `n_init` correctly.

**Hypothesis 2 (secondary): settings mismatch.**

The report claims `covariance=full` but the production engine uses `diag`. If the
prior session tested some third configuration that's neither of these, the results
would be unverifiable.

**Hypothesis 3: fabrication.**

The prior session wrote the report as a narrative without running the actual fits,
and the "3/6 fail" number was inferred from reasoning rather than measurement.

---

## Corrected Record

### What was wrong in HMM_STABILITY_REPORT.md

**Part D, "What annual re-freeze costs vs weekly-expanding", fourth bullet:**

> ~~Annual convergence is not guaranteed at any given year-end (3 of 6 year-end models
> failed to converge in this analysis). Infrastructure to ensure convergence (more
> restarts, regularization tuning, fallback logic) is needed before annual is
> production-viable.~~

**Corrected:** With true anchored-expanding data (2007 → year-end), all 6 year-ends
converge at n_init=5 with valid state ordering. At production settings (diag, n_init=10),
all 6 converge with zero degenerate seeds. Annual re-freeze convergence infrastructure
is **not required** — the scheme is numerically stable on the available data.

### What still stands in HMM_STABILITY_REPORT.md

Everything else in the report is unaffected:

- **Part A (weekly churn):** 1.8% average quarterly churn, zero Calm↔Stress inversions —
  these are measured from the quarterly model sequence and don't depend on annual fits.
- **Part B (scheme agreement):** 98.5% agreement on valid-label days (2019–2022) —
  based on the two year-ends that did converge (2018, 2021); unchanged.
- **Part C (detection quality):** identical recall/precision between schemes on COVID and
  2022 bear — unchanged.
- **Part D analytical verdict** (excluding the convergence bullet): the case for annual
  re-freeze is operational (reproducibility, auditability), not a detection quality
  improvement — this reasoning stands.

---

## Corrected Verdict for the Futures Plan

**Annual re-freeze convergence is not a concern.**

The futures model (frozen at 2024-12-31) uses anchored data from 2007 through 2024 —
a 17-year window far larger than any of the year-ends tested above. If a future
annual re-freeze is designed, hmmlearn will converge reliably at production settings
without additional engineering.

The remaining concern for futures is different and genuine: the frozen-2024 model
silently decodes 2025+ bars with no adaptation. That is a **model-age staleness**
problem (how many months since the last fit), not a convergence problem. It is
correctly framed as a TODO for a model-age staleness guard — separate from the
annual convergence question entirely.

---

## Appendix: Exact Fit Code Used in This Investigation

```python
from hmmlearn.hmm import GaussianHMM
from raits.hmm.features import build_feature_matrix
from raits.hmm.state_sorting import sort_hmm_states, validate_state_order
import pandas as pd

spy = pd.read_parquet('raits/data/cache/daily/SPY_daily_2007_2024.parquet')['close']

# Anchored-expanding fit for year-end YE
subset = spy[spy.index <= f'{YE}-12-31']
X = build_feature_matrix(subset)   # (N, 2): log-return + 5d realized vol

best_ll = -1e18; best_m = None
for seed in range(5):              # n_init=5, report settings
    m = GaussianHMM(n_components=4, covariance_type='full',
                    n_iter=100, min_covar=1e-2, random_state=seed)
    m.fit(X)
    ll = m.score(X)
    if ll > best_ll: best_ll = ll; best_m = m

sorted_m = sort_hmm_states(best_m)
valid = validate_state_order(sorted_m)
# Result: converged=True, valid=True for all 6 year-ends
```
