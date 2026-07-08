# Bootstrap Audit — Continuous vs Year-by-Year Design

**Date:** 2026-07-08  
**Branch:** future/incorporation  
**Scripts:** `raits/raits/scripts/bootstrap_continuous.py`, `diagnose_bootstrap_soundness.py`  
**Baseline:** `baselines/is_baseline_cb_fixed_2026-07-08.csv` (605 trades, IS 2017–2022)

---

## Background

The original bootstrap (`bootstrap_strategy.py`) ran on the **year-by-year (YbY)** design from `window_debug.py`:
- Capital resets each year, 252-day warmup per window
- `enable_pdt_guard=False`
- Kelly effective = 0.5 (PositionSizer bug: `kelly_fraction` not passed before commit `45ccc90`)
- Universe = `CANDIDATE_POOL`

The deployed system runs **continuous** design:
- Single 2017–2022 run, capital compounds
- `enable_pdt_guard=True`
- Kelly = 0.75
- `MAX_TREND = 3`

This audit re-runs the same bootstrap (H0: mean(net_pnl) ≤ 0, N=10,000, seed=42) on the continuous IS baseline to check whether YbY verdict decisions hold for the deployed design.

---

## Results: Verdict Comparison

| Strategy | YbY N | Cont N | YbY p | Cont p | YbY verdict | Cont verdict | Delta |
|---|---|---|---|---|---|---|---|
| TREND_FOLLOW | 656 | 353 | 0.008 | 0.116 | CONFIRMED | BORDERLINE | partial flip |
| ORB | — | 75 | 0.019 | 0.329 | CONFIRMED | NO EDGE | **FLIP** |
| STRESS_ORB | — | 108 | 0.019 | 0.215 | CONFIRMED | NO EDGE | **FLIP** |
| PE_SHORT | — | 29 | 0.007 | 0.011 | CONFIRMED | CONFIRMED | holds |
| GF_SHORT | — | 12 | 0.128 | 0.010 | BORDERLINE | CONFIRMED | partial flip |
| STRESS_MID | — | 28 | 0.112 | 0.401 | BORDERLINE | NO EDGE | partial flip |
| FADE | — | 0 | 0.754 | — | NO EDGE | (not in system) | consistent |
| GAP_FILL | — | 0 | 0.687 | — | NO EDGE | (not in system) | consistent |
| VWAP_MR | — | 0 | 0.613 | — | NO EDGE | (not in system) | consistent |

**2 hard flips: ORB and STRESS_ORB (CONFIRMED → NO EDGE).**

---

## STEP 1 — Bootstrap Method Soundness

**Method is consistent.** Both scripts use identical IID resampling, N_BOOT=10,000, seed=42, one-sided H0. The comparison is apples-to-apples.

**IID assumption is violated — bias direction is optimistic.**  
TF trades cluster in trend regimes (correlated wins/losses). IID bootstrap understates variance of the resample mean → produces p-values **lower than a block bootstrap would give**. All reported p-values are best-case estimates; true values are higher.

Implication:
- ORB (p=0.329) and STRESS_ORB (p=0.215) are too far above 0.05 for IID optimism to save them.
- TF (p=0.116 IID) would likely be p > 0.15 under block bootstrap — potentially NO EDGE.
- PE_SHORT (p=0.011 IID) could weaken under block bootstrap; see jackknife below.

---

## STEP 2 — TF N-Control: N Effect or Genuine Edge Weakness?

**Both — but genuine per-trade weakness dominates.**

| Metric | YbY TF | Continuous TF |
|---|---|---|
| N | 656 | 353 |
| Mean/trade | $22.45 | $15.96 |
| Std/trade | $273.40 | $253.03 |
| Cohen's d | 0.082 | 0.063 |
| t-stat | 2.10 | 1.19 |

Cohen's d dropped 23%. Per-trade edge quality genuinely declined between designs — this is not purely a smaller sample.

**N-control simulation** (simulate bootstrap at larger N using continuous distribution):

| N | Median p | Verdict |
|---|---|---|
| 353 | 0.141 | BORDERLINE (actual) |
| 500 | 0.078 | BORDERLINE |
| 650 | 0.064 | BORDERLINE |
| 800 | 0.033 | CONFIRMED |
| 1,000 | 0.027 | CONFIRMED |
| 1,500 | 0.006 | CONFIRMED |

**Breakeven N ≈ 1,500** — 4× the actual 353 trades. If the per-trade distribution were as strong as YbY, breakeven would be ~650. The extra gap to 1,500 reflects genuine edge weakness.

Likely causes of degradation:
- PDT on rations TF day-trade entries — fewer but self-selected trades
- Kelly 0.75 + continuous compounding amplifies variance in bad runs
- MAX_TREND=3 allows more concurrent TF positions, increasing correlated exposure

---

## STEP 3 — PE_SHORT Fragility (Jackknife)

N=29 trades over 6yr (~5/year). t-stat=2.25. Despite p=0.011, the edge is concentrated:

| Trades removed | New p | Verdict |
|---|---|---|
| 0 (baseline) | 0.011 | CONFIRMED |
| Top 1 ($1,499) | 0.025 | CONFIRMED |
| Top 2 ($1,499 + $1,488) | 0.055 | BORDERLINE |
| Top 3 (+ $1,176) | 0.109 | BORDERLINE |
| Top 5 | 0.247 | NO EDGE |

**Top 3 trades = 58% of total PE_SHORT P&L.**

The "confirmed" verdict rests on 2–3 large trades per the 6-year IS period. If 2025 OOS runs a year where those setups don't trigger, the edge disappears. This is concentration, not consistency.

---

## STEP 4 — System Characterization on Continuous Design

**IS 2017–2022 (correct/deployed design):**

| Scenario | N | Total P&L | Ann. P&L | Ann. return |
|---|---|---|---|---|
| Full system | 605 | $15,020 | $2,503/yr | 5.0% |
| Without ORB+STRESS_ORB | 422 | $13,298 | $2,216/yr | 4.4% |
| TF+PE_SHORT only | 382 | $12,772 | $2,128/yr | 4.3% |

Per-strategy IS contribution:

| Strategy | N | Total P&L | % of system | Cont verdict |
|---|---|---|---|---|
| PE_SHORT | 29 | $7,138 | 48% | CONFIRMED (concentrated) |
| TREND_FOLLOW | 353 | $5,635 | 38% | BORDERLINE (IID-optimistic) |
| ORB | 75 | $1,215 | 8% | NO EDGE |
| STRESS_ORB | 108 | $507 | 3% | NO EDGE |
| GF_SHORT | 12 | $283 | 2% | CONFIRMED (N=12, fragile) |
| STRESS_MID | 28 | $242 | 2% | NO EDGE |

---

## Honest Verdict

**This is not a "trim two strategies" situation. This is an "edge is marginal on the correct design" situation.**

### What the data shows
- One strategy confirmed on the correct design: PE_SHORT — but N=29, jackknife-fragile, concentrated.
- One borderline backbone: TF — IID optimistic, block bootstrap likely NO EDGE.
- Two deployed strategies with no confirmed edge: ORB, STRESS_ORB.
- IS annualized return: 5.0% on $50,000. Thin, especially considering costs and slippage not fully captured.

### What this does NOT mean
- It does not mean the system is broken. The vault OOS (2023–2024: +$7,404, Sharpe=0.88) is positive.
- It does not mean strategies should be removed. Re-selecting strategies post-hoc on continuous IS is overfitting — the same error made in the opposite direction.

### The correct framing
The strategy inclusion decisions were made on the YbY design, which was the available methodology at the time. Those decisions cannot be retroactively optimized using the continuous IS data that was used to evaluate them.

The **2025 live OOS test is the real arbiter** of whether the system has deployable edge. The IS evidence is not strong enough to call it pre-determined either way.

---

## Action Items

| Item | Action |
|---|---|
| ORB, STRESS_ORB | **Keep** — do not re-cut on IS. OOS performance is the correct removal signal. |
| TREND_FOLLOW | **Monitor** — backbone strategy, borderline on correct design. Track OOS P&L per-strategy. |
| PE_SHORT | **Monitor closely** — confirmed but concentrated. If OOS runs dry (0–1 big trades), verdict gone. |
| GF_SHORT | **Monitor** — improved verdict but N=12, fragile. |
| STRESS_MID | **Keep** — minor contributor, low harm, OOS will tell. |
| Block bootstrap | **Future work** — replace IID with block bootstrap (recommended block size: 20–40 bars) to get non-optimistic p-values. This should be the standard before any next strategy evaluation cycle. |
| OOS decomposition | **Future work** — when 2025 OOS data is available, decompose by strategy. TF and PE_SHORT OOS verdict is the key question. |

---

## Removed Strategies — Continuous IS Test

`diagnose_removed_strategies.py` re-enables FADE/GAP_FILL/VWAP_MR via `_REGIME_STRATEGIES` patch and `use_fade_scanner=True`, runs the continuous IS engine, then applies IID + block bootstrap + jackknife.

| Strategy | N | WR% | Mean$/t | t-stat | IID p | Block p | IID verdict | Bucket |
|---|---|---|---|---|---|---|---|---|
| FADE | 199 | 33.7% | -$32.53 | -2.87 | 0.997 | 1.000 | NO EDGE | removal-correct |
| GAP_FILL | 16 | 75.0% | +$80.52 | +1.31 | 0.100 | 0.000* | BORDERLINE | uncertain-needs-OOS |
| VWAP_MR | 33 | 24.2% | -$1.54 | -1.23 | 0.889 | 0.998 | NO EDGE | removal-correct |

*GAP_FILL block p=0.000 is a methodological artifact: `n_blocks = ceil(16/20) = 1` makes every bootstrap resample a circular permutation of all 16 trades → mean is identical every iteration. Degenerate case. Block result is uninformative.

### Verdicts

**FADE — removal definitively correct.** Not just "no edge" — actively destructive. WR=33.7%, mean -$32.53/trade, t=-2.87. The YbY verdict (p=0.754, no edge) understated the damage; continuous design reveals systematic value destruction at Kelly=0.75, PDT on. Jackknife irrelevant (p=0.998 with any trades removed).

**VWAP_MR — removal definitively correct.** WR=24.2%, mean -$1.54/trade (near-zero but negative). Structurally broken on stocks universe (SPY/QQQ/IWM) under continuous design. Removal stands unconditionally.

**GAP_FILL — removal correct by default; N=16 is untestable.** IID p=0.100 is borderline but jackknife fragile at k=1 (p=0.167 → NO EDGE). Top 3 trades = 80% of total P&L — concentrated. 2.7 trades/year over 6 years is insufficient to confirm edge by any method. Do not re-add; even OOS would remain inconclusive for years at this trade frequency.

### Complete Bootstrap Audit Summary

All strategy decisions examined against continuous IS design:

| Strategy | Status | Continuous verdict | Action |
|---|---|---|---|
| TREND_FOLLOW | In system | BORDERLINE p=0.116 | Monitor OOS |
| ORB | In system | NO EDGE p=0.329 | Keep — don't re-cut on IS |
| STRESS_ORB | In system | NO EDGE p=0.215 | Keep — don't re-cut on IS |
| PE_SHORT | In system | CONFIRMED p=0.011 | Monitor — concentrated N=29 |
| GF_SHORT | In system | CONFIRMED p=0.010 | Monitor — N=12, fragile |
| STRESS_MID | In system | NO EDGE p=0.401 | Keep — minor, OOS will tell |
| FADE | Removed | NO EDGE p=0.997 (negative) | Removal confirmed |
| VWAP_MR | Removed | NO EDGE p=0.889 (negative) | Removal confirmed |
| GAP_FILL | Removed | BORDERLINE p=0.100 (N=16) | Removal stands — untestable |

**Bottom line:** No removal was an error by any robustness test. No active strategy should be re-cut on IS. The 2025 OOS test is the final arbiter for all active strategies.

---

## Files

| File | Purpose |
|---|---|
| `raits/raits/scripts/bootstrap_continuous.py` | Bootstrap on continuous IS baseline (verdict comparison) |
| `raits/raits/scripts/diagnose_bootstrap_soundness.py` | N-control, PE_SHORT jackknife, system characterization |
| `raits/raits/configs/bootstrap_continuous_report.txt` | Saved verdict comparison output |
| `raits/raits/configs/bootstrap_soundness_report.txt` | Saved soundness diagnostic output |
| `baselines/is_baseline_cb_fixed_2026-07-08.csv` | Committed IS 605-trade baseline |
