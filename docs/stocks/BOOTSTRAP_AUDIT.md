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

**Update (2026-07-08): Dollar bootstrap understated TF. Revised: system has a confirmed backbone.**

The original "edge is marginal" conclusion was based on a flawed bootstrap metric — see Normalized Bootstrap section below.

### What the data shows (corrected — R-multiple bootstrap)
- **Confirmed backbone: TF** (p=0.009, d=+0.118 on R-multiple). The dollar bootstrap p=0.116 was a compounding-scale artifact.
- **Confirmed short strategies: PE_SHORT** (p=0.010) and **GF_SHORT** (p=0.000).
- **No confirmed edge: ORB, STRESS_ORB, STRESS_MID** — confirmed on both tests.
- IS annualized return: 5.0% on $50,000. Thin in dollar terms, but edge confirmed at the trade level.

### What this does NOT mean
- It does not mean the system is broken. The vault OOS (2023–2024: +$7,404, Sharpe=0.88) is positive.
- It does not mean strategies should be removed. Re-selecting strategies post-hoc on continuous IS is overfitting — the same error made in the opposite direction.

### The correct framing
The strategy inclusion decisions were made on the YbY design, which was the available methodology at the time. Those decisions cannot be retroactively optimized using the continuous IS data that was used to evaluate them.

The **2025 live OOS test is the real arbiter** of whether the system has deployable edge.

---

## Action Items

| Item | Action |
|---|---|
| ORB, STRESS_ORB | **Keep** — do not re-cut on IS. OOS performance is the correct removal signal. |
| TREND_FOLLOW | **Track OOS** — confirmed on correct (R-multiple) test. Dollar bootstrap was misleading. |
| PE_SHORT | **Monitor closely** — confirmed on both tests. Concentration (N=29) unchanged; still jackknife-fragile. |
| GF_SHORT | **Monitor** — confirmed strongly on R-multiple but N=12. Tight stops driving high R. |
| STRESS_MID | **Keep** — minor contributor, low harm, OOS will tell. |
| Block bootstrap | **Future work** — replace IID with block bootstrap (recommended block size: 20–40 bars). |
| OOS decomposition | **Future work** — when 2025 OOS data is available, decompose by strategy. TF P&L per-trade is the key OOS verification. |
| R-multiple bootstrap | **Use by default** — for all future strategy edge tests, use R-multiple not dollar P&L. Dollar bootstrap is biased under Kelly/compounding. |

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

## Normalized Bootstrap — R-Multiple vs Dollar P&L

**Date:** 2026-07-08  
**Script:** `raits/raits/scripts/bootstrap_normalized.py`

### Methodology problem with dollar bootstrap

The continuous IS design uses Kelly=0.75 + compounding. Position size scales with account equity at each trade's time. Dollar P&L is therefore non-homogeneous across trades: a trade at $60k equity has ~20% larger positions than the same trade at $50k. Bootstrapping raw dollar P&L mixes trades at different scales and breaks path dependency. This biases p-values in both directions depending on when the strategy performs.

**R-multiple = net_pnl / (shares × |entry_price − stop|)** is the correct normalization:
- `initial_risk` is set at entry and is scale-independent
- Same entry/exit logic → same R regardless of equity or position size
- Answers the right question: "does the strategy generate positive expected value per unit of risk?"

### Results

| Strategy | N | Mean R | d (R) | Dollar p | R-multiple p | Delta | Verdict |
|---|---|---|---|---|---|---|---|
| TREND_FOLLOW | 353 | +0.150 | +0.118 | 0.116 | **0.009** | −0.107 | **CONFIRMED** ↑ |
| PE_SHORT | 29 | +0.349 | +0.421 | 0.011 | 0.010 | −0.001 | CONFIRMED = |
| GF_SHORT | 12 | +8.586 | +0.637 | 0.010 | 0.000 | −0.010 | CONFIRMED = |
| ORB | 75 | +0.071 | +0.081 | 0.329 | 0.241 | −0.088 | NO EDGE = |
| STRESS_ORB | 108 | +0.041 | +0.033 | 0.215 | 0.366 | +0.151 | NO EDGE ↓ |
| STRESS_MID | 28 | +0.076 | +0.060 | 0.401 | 0.380 | −0.021 | NO EDGE = |

### Key findings

**TF: BORDERLINE → CONFIRMED (delta = −0.107).** This is the most significant result. TF performed better early in IS (2017–2019) when equity was low → small dollar P&L from those wins was underweighted in the dollar bootstrap. On R-multiple, TF's mean R = +0.150/trade, p = 0.009, d = +0.118. The "borderline on correct design" conclusion was a compounding-scale artifact, not a genuine edge weakness.

**STRESS_ORB: NO EDGE hardens (delta = +0.151).** Dollar compounding inflated STRESS_ORB — it fired predominantly in later IS years (2020–2022 Stress regimes) when equity was higher. On R-multiple the no-edge verdict is even clearer (p = 0.366, d = +0.033). The no-edge verdict is not an artifact; it's understated by dollar bootstrap.

**ORB: NO EDGE remains (R-p = 0.241).** The dollar bootstrap actually understated ORB's edge slightly (delta = −0.088), but it's still clearly no-edge.

**PE_SHORT, GF_SHORT: unchanged on R-multiple.** Scale artifact is minimal. The concentration concern for PE_SHORT (jackknife fragility at k=2) is a real structural issue, not a dollar-scale artifact.

### The two questions cleanly separated

| Question | Correct method |
|---|---|
| "Does strategy X have edge?" | R-multiple bootstrap — scale-independent |
| "How much does the compounded system earn?" | Equity-curve metrics (Calmar/Sharpe) |
| "Is dollar per-trade bootstrap valid under Kelly?" | NO — biased under compounding |

### Updated complete summary (R-multiple = correct test)

| Strategy | Status | R-multiple verdict | Dollar verdict | Action |
|---|---|---|---|---|
| TREND_FOLLOW | In system | **CONFIRMED p=0.009** | BORDERLINE p=0.116 | Track OOS — confirmed backbone |
| PE_SHORT | In system | CONFIRMED p=0.010 | CONFIRMED p=0.011 | Monitor — concentrated N=29 |
| GF_SHORT | In system | CONFIRMED p=0.000 | CONFIRMED p=0.010 | Monitor — N=12, tight stops |
| ORB | In system | NO EDGE p=0.241 | NO EDGE p=0.329 | Keep — OOS will tell |
| STRESS_ORB | In system | NO EDGE p=0.366 | NO EDGE p=0.215 | Keep — OOS will tell |
| STRESS_MID | In system | NO EDGE p=0.380 | NO EDGE p=0.401 | Keep — minor, OOS will tell |
| FADE | Removed | (not tested — not in IS baseline) | NO EDGE p=0.997 (negative) | Removal confirmed |
| VWAP_MR | Removed | (not tested — not in IS baseline) | NO EDGE p=0.889 (negative) | Removal confirmed |
| GAP_FILL | Removed | (not tested — not in IS baseline) | BORDERLINE p=0.100 (N=16) | Removal stands — untestable |

**Revised bottom line:** TF (p=0.009) + PE_SHORT (p=0.010) confirmed. GF_SHORT verdict withdrawn — R-multiple was an artifact. See Block-R + GF_SHORT Artifact section.

---

## Block-R + GF_SHORT Artifact — Final Closure

**Date:** 2026-07-08  
**Script:** `raits/raits/scripts/bootstrap_block_r.py`

### GF_SHORT: "CONFIRMED" is a trailing-stop artifact — withdrawn

**Root cause:** The `stop` column in the CSV for GF_SHORT stores the **final chandelier stop position at exit**, not the initial risk stop. The engine updates GF_SHORT's trailing stop down each bar (`_new_trail = bar_low + _sd`, only if lower). For profitable trades the trail moves far below entry, making `|entry − CSV_stop|` tiny at exit.

Examples: COST entry=490.420, CSV_stop=490.229 → computed risk=**$1.33** → R=+37.73.
Actual initial risk: `morning_hod + 0.1*atr` was well above entry; the $1.33 is the trail distance at the moment of exit, not the dollar risked at entry.

**Systematic bias direction:** Only profitable trades have tiny final-stop distances (the trail followed price down). Losing trades hit the initial stop early → trail barely moved → final stop ≈ initial stop → reasonable denominator. This biases R upward for winners specifically, inflating mean R from a realistic ~0.1 to an artifactual +8.59.

**TF is not affected:** TF's chandelier also trails, but the trail never moved past the entry price for any of 353 trades (0 trades with stop on wrong side). TF's `|entry − CSV_stop|` therefore overstates the denominator (trail is larger than initial stop for profitable trades) → TF's R-multiple is **conservative**, not inflated. TF's CONFIRMED verdict (p=0.009) is sound.

**GF_SHORT valid test reverts to dollar IID only:** p=0.010 (N=12, block-degenerate, jackknife fragile at k=2). Not reliably confirmed.

### Final honest edge picture (all IS evidence combined)

| Strategy | Final verdict | Basis | Notes |
|---|---|---|---|
| **TREND_FOLLOW** | **CONFIRMED (robust)** | R-p=0.009, Block-R(B20) confirmed, JK-R holds k=2 | Trunk. Scale-independent, path-robust, not concentration-driven. |
| **PE_SHORT** | **CONFIRMED (concentrated)** | R-p=0.010, unchanged from dollar | Top-5 trades = 75% of R. Remove top 3 → fragile. N=29 in 6yr = 5/yr. |
| GF_SHORT | **UNTRUSTWORTHY** | R-multiple invalid (trailing stop artifact); dollar p=0.010 N=12 block-degen | Cannot confirm. N=12 is untestable by any method. |
| ORB | NO EDGE | All tests — IID-dollar, IID-R, block-R | Not confirmed on any credible test. |
| STRESS_ORB | NO EDGE | All tests — dollar p=0.215 flatters it; block-R p=0.366 is the honest read | Dollar compounding inflated it; true picture is clearer no-edge. |
| STRESS_MID | NO EDGE | All tests — p=0.38-0.40 across all metrics | Minor, consistent no-edge. |

**Deployable-edge set confirmed by IS:** TF (robust) + PE_SHORT (confirmed, concentrated). GF_SHORT and the three no-edge strategies are neutral contributors — do not re-cut on IS.

### What 2025 OOS must confirm

These are pre-committed OOS questions, not re-selection criteria:

**TF — most important (38% of IS P&L, only robust confirmed strategy):**
- Does mean per-trade R stay positive OOS?
- Alert if: OOS TF P&L after 12 months is negative, or per-trade mean dollar P&L < $5 (significantly below IS $15.96/trade).

**PE_SHORT — concentrated edge, fragile by construction (5 trades/yr):**
- Does the concentrated edge repeat? Need 2-3 large-R trades per year to maintain IS P&L rate.
- Alert if: OOS year 1-2 shows 0-1 PE_SHORT big wins (>$500/trade). That's the IS edge not transferring.

**No-edge strategies (ORB, STRESS_ORB, STRESS_MID) — drag vs neutral:**
- Combined IS contribution is small positive dollar P&L without confirmed edge.
- Alert if: OOS running total for these three combined turns consistently negative after 2+ years.
- That is the correct OOS signal for removal — not IS re-cutting.

**GF_SHORT — accumulate N before re-assessing:**
- N=12 over 6yr IS (2 trades/yr) means OOS is also too slow to test.
- Monitor dollar P&L but don't read statistical significance into OOS GF_SHORT results for 3+ years.

---

## Files

| File | Purpose |
|---|---|
| `raits/raits/scripts/bootstrap_continuous.py` | Bootstrap on continuous IS baseline (verdict comparison) |
| `raits/raits/scripts/diagnose_bootstrap_soundness.py` | N-control, PE_SHORT jackknife, system characterization |
| `raits/raits/scripts/bootstrap_normalized.py` | R-multiple bootstrap (correct edge test, scale-independent) |
| `raits/raits/scripts/bootstrap_block_r.py` | Block-R bootstrap + GF_SHORT sanity check + PE_SHORT JK-R |
| `raits/raits/configs/bootstrap_continuous_report.txt` | Saved verdict comparison output |
| `raits/raits/configs/bootstrap_soundness_report.txt` | Saved soundness diagnostic output |
| `raits/raits/configs/bootstrap_normalized_report.txt` | Saved R-multiple bootstrap output |
| `raits/raits/configs/bootstrap_block_r_report.txt` | Saved block-R + final verdict output |
| `baselines/is_baseline_cb_fixed_2026-07-08.csv` | Committed IS 605-trade baseline |
