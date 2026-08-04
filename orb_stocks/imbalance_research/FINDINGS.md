# Opening Imbalance Filter for ORB — research report

**Status: MONITOR** (not GO, not dead)
**Date:** 2026-08-03 · **Scope:** research only — no production code touched, no merge implied.

Research track: `orb_stocks/imbalance_research/`. Follows the catalyst study's
three-layer method (`check_news_coverage.py` → `bootstrap_catalyst.py` →
`cluster_bootstrap.py`), with the same event population and the same outcome
definition, so the two results are directly comparable.

---

## Headline

Pre-open signed order flow, measured 09:00–09:30 ET, separates outcomes on the
existing SHORT ORB / STRESS_ORB_STK setup: events where flow agreed with the
trade returned **+0.253%** vs **−0.094%** when it disagreed (diff **+0.347%**),
and the deciding within-date conditional test gives **p = 0.0267**.

It does **not** clear the concentration bar. Dropping either of two single
tickers breaks p < 0.05, and the effect is present only in 2022. Under the rule
fixed before the checks were run — *a GO that breaks on any single ticker is a
concentration artifact* — this is **MONITOR**.

Two findings below matter more than the headline: the data that the hypothesis
was actually about **does not exist on this plan**, and the catalyst study's
permutation test **has a centring bug** that this study inherited and fixed.

---

## Step 1 — Coverage (verdict: GO)

`check_imbalance_coverage.py` — pre-committed thresholds written before the
first fetch (GO ≥80% overall and ≥70% per year and ≥25 dates; NO-GO <50%).

### What is *not* available — the hypothesis had to change

| Source | Status | Consequence |
|---|---|---|
| NYSE/Nasdaq published auction imbalance | **absent** (404 on both probed paths) | the prompt's first-choice input does not exist here |
| Polygon NBBO quotes (`/v3/quotes`) | **403 NOT_AUTHORIZED** | canonical Lee-Ready is **not constructible** — it needs the quote midpoint |
| Polygon trades (`/v3/trades`) | **available**, 2021–2022, conditions included | only the **tick rule** remains |

The prompt's note ("ưu tiên dùng Lee-Ready vì đã có tick data qua Polygon")
assumed quotes were entitled. They are not. Lee-Ready is a *quote*-based
classifier; without NBBO only its fallback tie-breaker — the tick rule — can be
run standalone.

**This changes what was tested.** The measured object is *pre-open signed order
flow via the tick rule*, not the opening auction imbalance. Different window,
different mechanism, weaker classifier. A null here would not have cleared the
official-imbalance hypothesis, and the positive result here is not evidence
about the auction imbalance either.

Mitigating: tick-rule classification quality is high on this tape — unclassified
volume is **0.0% median, 1.0% at p90** — so the classifier is not the weak link.

### Coverage (155 events, 31 tickers, 82 dates, 2021-04-28 → 2022-12-27)

| Window | Usable (≥30 classified trades) | 2021 | 2022 | Dates |
|---|---|---|---|---|
| `full` 04:00–09:30 ET | **155/155 (100%)** | 33/33 | 122/122 | 82 |
| `late` 09:00–09:30 ET | 151/155 (97.4%) | 32/33 | 119/122 | 81 |

Coverage is not the binding constraint. Depth is heavily skewed (median 795
classified trades in the late window, but BIIB 7 and TSLA 10,620) — as expected
for pre-market tape, and handled by the ≥30 floor rather than assumed away.

---

## Step 2 — Features and confounds (requirement #2 and #4)

`build_imbalance_features.py`.

**Test variable chosen from the data, not imposed.** Magnitude passes the
distribution screen in the `late` window but fails in `full` (skew +1.42); no
event is pinned at |ratio|>0.99 in either. **Direction** is well-balanced
(late: 114 sell-side / 38 buy-side) and needs no baseline or distributional
assumption, so direction is the primary variable — the same reasoning that made
`is_idiosyncratic` the testable variable in the catalyst study.

**Confound check — this is the strongest part of the result.** Signed flow is
essentially uncorrelated with the price-action features already tested dead:

| Feature pair (late window) | Pearson | Spearman |
|---|---|---|
| `imb_ratio_vol` vs `gap_pct` | +0.014 | **+0.028** (p=0.73) |
| `imb_ratio_vol` vs pre-market volume rank (RVol proxy) | +0.014 | −0.016 (p=0.84) |
| `imb_magnitude` vs `gap_pct` | +0.098 | +0.056 |

The raw sign-agreement between flow and gap is 74%, which looks alarming until
the base rates are applied: this population is **98% down-gap** and 75%
sell-side, so chance agreement alone is 74%. **Cohen's κ = +0.013** — no
association beyond base rates.

So requirement #2 is satisfied: this is not H1–H3 wearing a hat. Whatever the
signal is, it is orthogonal to gap and to pre-market volume.

*Caveat on `imb_z_loo`:* the within-ticker baseline is built from that ticker's
**other event days**, not from all trading days. It removes the ticker's level
but not the "this is an event day" conditioning. A true all-days baseline needs
~650 extra fetch-days and was deferred — it is a revisit condition below.

---

## Step 3 — Three-layer test

`bootstrap_imbalance.py`. Primary cell pre-committed as `late` × `pct_return`
(the auction analogue × the catalyst study's own outcome metric); the other
three cells are secondary and can only downgrade, never promote.

### A defect found and fixed in the inherited method

The catalyst study's `cluster_bootstrap.py` computes the within-date
permutation p as `|perm| >= |obs|` — distance from **zero**. But events on
non-mixed dates have no label freedom, so their contribution is a constant
present in `obs` and in every permuted draw alike. The null is centred on that
offset, not on zero.

Measured on this study's primary cell: **null centre = +0.123%**, not 0.
Uncentred p = **0.0129**; correctly centred p = **0.0267**. The uncentred form
**overstated significance by ~2×**.

Fixed here (`layer3()` centres on the null's own mean and reports both).
**This bug is still live in `orb_stocks/cluster_bootstrap.py`.** It does not
overturn the catalyst verdict — that p was 0.524, far from any threshold — but
the number in that write-up is not the number that test should have produced,
and any future reuse of that script will inherit the bias.

### Results

| Cell | n | Layer 1 naive | Layer 2 cluster | **Layer 3 within-date** | Dir. |
|---|---|---|---|---|---|
| **`late` × pct_return** (primary) | 144 | 0.157 | 0.100 | **0.0267** | consistent |
| `late` × R_multiple | 144 | 0.291 | 0.183 | 0.0863 | consistent |
| `full` × pct_return | 147 | 0.640 | 0.628 | 0.167 | **sign flips vs primary** |
| `full` × R_multiple | 147 | 0.542 | 0.514 | 0.218 | **sign flips vs primary** |

Primary cell detail: aligned n=110 mean **+0.253%** (WR 56%) vs against n=34
mean **−0.094%** (WR 47%), diff **+0.347%**.

**Clustering:** ICC = 0.368, design effect 1.329, **effective n = 108.3** (raw 144).

**This is the opposite pattern to the catalyst study.** There, naive was strong
(P(A>B)=0.94) and the within-date test killed it (0.524) — a between-date
artifact. Here naive is *weak* (0.157) and within-date is *stronger* (0.0267).
That direction of change is legitimate and expected when date effects are
large (ICC=0.37): conditioning on date removes between-day noise that was
swamping a within-day contrast. It is the standard argument for a blocked
design — but it also means the result rests on a much smaller base than n=144
suggests (see below).

---

## Step 3b — Robustness (this is what downgrades the verdict)

`robustness_imbalance.py`. Rule fixed before running: *a GO that breaks on any
single ticker or single date is a concentration artifact and must be
downgraded, regardless of the headline p-value.*

| Check | Result | Passes? |
|---|---|---|
| Leave-one-ticker-out | **QCOM (5 ev) → p=0.102**; **NVDA (10 ev) → p=0.065**; other 14 tickers hold | **NO** |
| Leave-one-date-out | 1 of 23 dates breaks it (2022-02-04 → p=0.073) | marginal |
| Winsorise ±2 sd (7 rows clipped) | p 0.027 → 0.033, diff +0.347% → +0.279% | **YES** — not tail-driven |
| Year split | **2022: p=0.020** (n=116) · **2021: p=0.528** (n=28, only 4 mixed dates) | **NO** — 2022 only |

### Why 5 events can move the p-value that much

The deciding test does not run on 144 events. Only **mixed dates** — those
carrying both an aligned and an against event — have label freedom. That is
**23 dates / 63 events (35 aligned, 28 against)**. The "against" arm of the
actual contrast is 28 events, and QCOM contributes 2 of them at −0.593%.

So the honest effective sample for the deciding test is ~63 events, not the
108.3 the design-effect calculation reports for the full population. The
ticker sensitivity is a direct consequence and was predictable from that
structure.

---

## Verdict: MONITOR

Not GO: fails the pre-committed concentration rule on two tickers, and the
effect is confined to 2022. Not dead: the direction is consistent across all
three layers, it survives winsorising, the confound check is genuinely clean
(κ=+0.013), and the mechanism is economically sensible — shorting into
confirmed pre-open selling pressure.

2021 is best read as **unconfirmed rather than contradictory**: n=28 with only
4 mixed dates has almost no power for the deciding test.

**Against promoting this further:** the `full`-window cells point the *opposite*
way (−0.10%). Defensible — the 4am–8am tape is mostly noise and the 09:00–09:30
window is where auction-relevant flow concentrates — but it is not confirmation,
and if the effect were robust some directional agreement would be expected.
Also, with 4 cells examined, a Bonferroni-style read of the primary would give
0.0267 × 4 ≈ 0.107. The primary *was* pre-committed, so no correction is
formally required; it is stated so the number is not oversold.

### What would settle it (revisit conditions)

1. **More mixed dates.** The deciding test's power is set by mixed-date count
   (currently 23). This is the binding constraint, not total event count.
   **→ ADDRESSED 2026-08-03, at zero data cost.** The 2021-04 window start was
   inherited from the catalyst study, where it was set by Polygon's *news*
   history onset — a constraint that does not apply to this study, which uses
   no news. The committed sim already produces events back to 2018-02, and
   `window_debug_5min.pkl` covers 2017-01→2024-12 with no gap. Rebuilding over
   2018-05→2022-12 (`build_extended_event_index.py`):

   | | old | extended |
   |---|---|---|
   | clean events | 154 | **267** (×1.73) |
   | dates | 81 | **150** |
   | dates with ≥2 events (mixed-date ceiling) | 45 | **72** (×1.60) |
   | years covered | 2 | **5** (2018–2022) |

   Expected mixed dates ≈ 36 (applying the observed 23/45 = 51% split rate to
   the new ceiling) vs 23 now. Start is 2018-05-01 to match Databento's
   imbalance history; 6 events on 2 dates before that are dropped and reported.

2. **2023+ or OOS Stress data** — would test whether the 2022-only pattern is
   regime-specific or sample-specific. Partly addressed by (1): the extended
   index adds 2018 (20 ev), 2019 (24 ev) and 2020 (56 ev), so the year-split
   robustness check stops being a two-year comparison. 2023+ remains genuinely
   out-of-sample and is still the stronger test.
3. **NBBO quotes** (plan upgrade) → real quote-based Lee-Ready. The tick rule
   is strictly weaker; a genuine signal could be attenuated by classification
   error, so the current estimate is more likely a floor than a ceiling.
4. **Official auction imbalance data**, if ever sourced — the hypothesis as
   originally written has still never actually been tested.
5. **True all-days within-ticker baseline** (~650 fetch-days) so `imb_z_loo`
   stops being conditioned on event days, enabling the magnitude/z-score
   variants as genuine secondary tests.

**No production change is implied or authorised by this report.** Per the
prompt, even a GO would only have meant "enough basis to *design* a
filter/confirm layer" — a separate decision. MONITOR is below that bar.

---

## Files

| File | Role |
|---|---|
| `check_imbalance_coverage.py` | Step 1 — entitlement probe + per-event tick coverage; caches signed aggregates |
| `build_imbalance_features.py` | Step 2 — features, distribution screen, confound check |
| `bootstrap_imbalance.py` | Step 3 — three-layer test (centred permutation) |
| `robustness_imbalance.py` | Step 3b — ticker/date jackknife, winsorise, year split |
| `imbalance_coverage.parquet` | 155 events × signed aggregates, both windows (cached ticks) |
| `imbalance_features.parquet` | 152 events × features (3 gap_suspect dropped) |
| `imbalance_test_results.parquet` | 4 cells × test statistics |

Reused unchanged: `raits/data/cache/news/orb_event_index.parquet` (event
population) and `orb_event_outcome.parquet` (pct_return / R_multiple, with the
catalyst study's |pct|>25% corrupt-bar gate).

Reproduce:
```
cd d:\raits
python orb_stocks\imbalance_research\check_imbalance_coverage.py --resume
python orb_stocks\imbalance_research\build_imbalance_features.py
python orb_stocks\imbalance_research\bootstrap_imbalance.py
python orb_stocks\imbalance_research\robustness_imbalance.py
```
