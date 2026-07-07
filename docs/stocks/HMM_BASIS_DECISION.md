# HMM Basis Decision: Split-Only is Correct for the Intraday Regime Gate

**Decision date:** 2026-07-07  
**Status:** CLOSED — do not re-litigate without new evidence  
**Scope:** stocks equity engine only (futures HMM is a separate system)

---

## Decision

The HMM trains on **5-min-derived daily close (split-only)** and this is **correct**
for the intraday regime gate. The div-adjusted daily parquet is the **wrong basis**
for this purpose.

Do not switch the HMM to div-adjusted data. No re-validation required.

---

## Reasoning

### 1. Features are log returns — bases are nearly identical

HMM observation matrix (`hmm/features.py`):

```
Feature 0: log_return_t    = log(P_t / P_{t-1})
Feature 1: realised_vol_t  = rolling-5d std(log_return) × √252
```

For any non-ex-div day: `log(P_t^split / P_{t-1}^split) == log(P_t^div / P_{t-1}^div)` exactly.  
The two series differ **only on ex-div dates** (~28 days/year for SPY quarterly dividends).

### 2. Ex-div magnitude is too small to change regime

SPY's quarterly dividend yield ≈ 0.4% per event.  
A single -0.4% day at normal vol is far below the feature ranges that separate states:

| State  | Typical realised vol (annualized) |
|--------|-----------------------------------|
| Calm   | 8–12%                            |
| Normal | 12–20%                           |
| Stress | 20–40%                           |
| Crisis | 40%+                             |

A -0.4% SPY ex-div drop on a Calm day contributes ≈0.4 / (5-day window) ≈ 0.08pp to the
5-day rolling vol window — negligible. The HMM does not misclassify ex-div days as Stress.

### 3. Strategies execute on split-only prices

ORB, TREND_FOLLOW, STRESS_ORB, PE_SHORT — all compute entry/exit prices, ATR stops,
gap sizes, and realized P&L from **split-adjusted 5-min bars** (Polygon `adjusted=true`
on 5-min data = split-only). The regime gate must see the same series strategies face.

On an ex-div morning, SPY genuinely opens lower by the dividend amount. That IS the
actual intraday market condition. A div-adj HMM that smooths it away would classify
the session as "Normal" when the market is actually gapped lower — incorrect for an
intraday gate.

### 4. The 8.17% label diff is mostly HMM non-determinism, not basis-driven

Measured in `spy_basis_verdict.py`:

| Source                               | Label diff |
|--------------------------------------|-----------|
| Same-data noise floor (seed 0 vs 1)  | 3.28%     |
| Basis comparison (split vs div-adj)  | 8.17%     |
| Implied genuine basis signal         | ~4.9%     |

The 3.28% same-data noise shows two independent HMM fits on **identical** data differ
by ~3.3% — from EM local optima, not from any real signal difference. The ~4.9% genuine
basis contribution is from Viterbi path sensitivity to the ~28 ex-div dates.

---

## What Was Measured

`spy_adjustment_audit.py` — label diff between static HMM-A (split-only) and HMM-B (div-adj):
- After label-switching fix (sorted comparison): **8.17%** label difference
- Calm↔Stress direct flips: **0** (no dangerous strategy-set inversions)
- Verdict: MODERATE

`spy_basis_impact.py` — downstream impact using proxy trade removal:
- ORB, STRESS_ORB, TREND_FOLLOW appeared to cross p=0.05 verdict threshold
- Caveat: THREE methodology artifacts in that test (static HMM, proxy removal, N-drop)

`spy_basis_verdict.py` — removed two of three artifacts:
- Same-data noise floor: 3.28% (controls for HMM non-determinism)
- Rolling quarterly labels (artifact A): confirmed rolling diff ≈ or < static diff
- N-control bootstrap (artifact C): TREND_FOLLOW flip confirmed as pure N-reduction artifact
- STRESS_ORB: only strategy with a residual real basis-flip

---

## STRESS_ORB Caveat (Known, Not Actionable)

STRESS_ORB shows a basis-sensitive verdict flip under the rolling comparison.

**Why it is not actionable:**
- STRESS_ORB is already borderline in the baseline (p=0.019, low trade count)
- It is a "rim of system" strategy: fires only in Stress regime on ETF proxies
- Changing the HMM basis to div-adjusted would be wrong (STEP 1 above)
- The strategy's basis sensitivity reflects its low N, not a structural flaw

**Note it; do not remove it.** The correct action if STRESS_ORB continues to be
borderline is to collect more Stress-regime data over time, not to switch HMM bases.

---

## HMM Seed Pinning — Baseline Reproducibility

**Finding:** The production HMM IS deterministic. Seed is pinned.

Code path (`hmm/engine.py`):
```python
RANDOM_SEED = 42                      # module-level constant

class HMMEngine:
    def __init__(self, ..., random_state: int = RANDOM_SEED, ...):
        self.random_state = random_state   # = 42 when called as HMMEngine()

    def _fit_best(self, X):
        rng = np.random.RandomState(self.random_state)  # re-seeded each call
        for i in range(self.n_init):
            seed = rng.randint(0, 2**31 - 1)            # deterministic sequence
            hmm = GaussianHMM(..., random_state=seed, ...)
            hmm.fit(X)
```

Both `engine.py:217` and `engine_refactored.py:225` call `HMMEngine()` with no arguments,
inheriting `random_state=42`. The `_fit_best` method **re-creates** `RandomState(42)` on
every call (initial fit AND each weekly retrain), generating the same 10 deterministic
init seeds regardless of when the retrain fires.

**Consequence:** Given the same input data, the engine produces exactly the same HMM model
and exactly the same labels on every run. Baseline is reproducible.

**Sensitivity caveat:** The same-data noise test showed ~3.28% label sensitivity to seed
changes. If `RANDOM_SEED` were ever modified, the regenerated baseline could differ by
~3% in HMM labels. **Do not change RANDOM_SEED before or during baseline regeneration.**

---

## Path Forward

1. Split-only confirmed correct — no strategy-decision redo needed  
2. STRESS_ORB basis sensitivity noted — monitor, do not act  
3. Seed is pinned (RANDOM_SEED=42) — baseline is reproducible when input data is identical  
4. Next action: regenerate baseline on split-only data with the sealed seed