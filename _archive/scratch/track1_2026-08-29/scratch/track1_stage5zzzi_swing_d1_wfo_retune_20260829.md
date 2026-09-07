# Stage 5ZZZ-I — retuning Swing under causal D-1 labels

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

## Decision

# `KEEP_RESEARCH_ONLY`

The retune ran. It selected `ema=10, mult=2.5`, and **that choice is worse out-of-sample than the parameters it replaced** — Swing's own contribution is negative in *both* OOS windows. The brief's own bar — *do not promote unless OOS evidence supports it* — is not met. Swing stays enabled in shadow, and is not paper-orderable.

**Best causal D-1 params found: `ema_period=10, chandelier_atr_mult=2.5, max_hold_days=5`** — selected in 4 of 10 folds. A plurality, not a majority, and it does not survive contact with 2025 or 2026.

---

## 1. The original process, recovered

`futures/basket.py` credits the frozen `{"ema_period": 30, "chandelier_atr_mult": 2.5, "max_hold_days": 5}` to a *"pooled WFO winner, 5/6 folds"*, and the script inventory names `pooled_swing_wfo.py`. That script gives the whole protocol:

```text
grid       ema_period in {10, 20, 30}  x  chandelier_atr_mult in {2.5, 3.0, 3.5}
max_hold   5, fixed - never in the grid
objective  Calmar on the TRAIN fold, minimum 10 basket trades
folds      rolling 18 months train -> 6 months test, stepping 6 months
pooling    one shared parameter per fold, across the whole basket
labels     label_regimes(...) raw -> labels.get(day)  = the session's own label
```

### A provenance gap, reported as one

Running that protocol on its own configuration reproduces the **fold geometry exactly — 6 folds** — and does **not** reproduce the frozen parameter:

| reading | winner | ema30/mult2.5 placed |
|---|---|---|
| fold vote, original config | ema10/2.5 (2/6) | 1 of 6 folds |
| pooled whole-region Calmar, original config | ema10/2.5 (Calmar 1.81) | 4th, Calmar 1.11 |
| pooled whole-region Calmar, Track 1 floor config | ema20/2.5 (Calmar 1.35) | 3rd, Calmar 0.91 |

**This is "could not be reproduced", not "is wrong".** The recorded provenance of the parameter Track 1 Swing runs today cannot be reconstructed from the script the repo names for it, with the data and configurations available here. It is a separate finding from anything about D-1, and it deserves its own answer.

Because of it, this stage does **not** claim to have re-run the original tuning. What it runs is a **controlled A/B**: one protocol, one configuration, one dataset, applied identically to both label sets, so the difference is attributable to the label and nothing else.

---

## 2. What the retune selected

Selection used the **floor region only**. 2025 and 2026 were never read.

| arm | winner | fold share | full spread |
|---|---|---|---|
| same-day (control) | ema10/2.5 | 4/10 | ema10/2.5 ×4 · ema20/2.5 ×4 · ema20/3.5 ×1 · ema30/2.5 ×1 |
| **causal D-1** | **ema10/2.5** | **4/10** | ema10/2.5 ×4 · ema30/2.5 ×2 · ema20/2.5 ×2 · ema10/3.5 ×1 · ema20/3.0 ×1 |

Two things are worth saying out loud before any number below is read:

- **No parameter wins a majority in either arm.** The control has a two-way tie at 4. This objective, on this grid, does not find a stable choice — under either label.
- **The frozen ema30/mult2.5 is selected in 1 of 10 folds under same-day and 2 of 10 under D-1.** It is not what this procedure picks either way.

The D-1 folds, in order — the parameter moves almost every time, and one fold is negative:

```text
2019-07 -> 2020-01   ema=10 mult=2.5    94t   $  305   Calmar  1.87
2020-01 -> 2020-07   ema=10 mult=3.5   213t   $3,537   Calmar  1.89
2020-07 -> 2021-01   ema=30 mult=2.5   200t   $6,649   Calmar  8.94
2021-01 -> 2021-07   ema=30 mult=2.5   161t   $ -559   Calmar -0.61
2021-07 -> 2022-01   ema=20 mult=2.5   111t   $3,809   Calmar  7.87
2022-01 -> 2022-07   ema=10 mult=2.5   302t   $7,600   Calmar  4.53
2022-07 -> 2023-01   ema=10 mult=2.5   304t   $1,464   Calmar  0.55
2023-01 -> 2023-07   ema=10 mult=2.5   227t   $1,265   Calmar  0.89
2023-07 -> 2024-01   ema=20 mult=2.5   127t   $4,036   Calmar  4.38
2024-01 -> 2024-07   ema=20 mult=3.0    81t   $5,413   Calmar 21.97
```

---

## 3. Four routes through the same replay

Account $50,000 · 1 micro · 2 ticks/side · family cap 5.0%/4.4% · production fill law · HMM fit end per window. The 2026-08-21 baseline reproduced 30/30 before anything was compared.

### Full stack, Calm-NKD ON

| Window | Route | Net | PF | Sharpe | Calmar | MaxDD | trades | Swing $ | Swing taken/rej |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **floor** *(in-sample)* | same-day *(not live-tradable)* | $74,410 | 1.67 | 2.12 | 2.14 | $4,973 | 1690 | $25,677 | 545/190 |
| | D-1, old params | $66,796 | 1.59 | 1.91 | 1.92 | $4,973 | 1696 | $18,429 | 564/197 |
| | **D-1, retuned** | $64,374 | 1.55 | 1.83 | 1.78 | $5,186 | 1710 | $16,883 | 580/211 |
| | no Swing | $49,414 | **1.82** | **2.19** | 1.84 | **$3,842** | 1156 | $0 | — |
| **2025** *(OOS)* | same-day *(not live-tradable)* | $16,997 | 2.26 | 2.76 | 4.45 | $3,901 | 214 | $4,690 | 55/48 |
| | D-1, old params | $16,181 | 2.05 | 2.50 | 3.36 | $4,915 | 215 | $3,906 | 57/48 |
| | **D-1, retuned** | $10,040 | 1.66 | 2.16 | 2.52 | $4,065 | 221 | **−$2,190** | 62/42 |
| | no Swing | $12,377 | **3.01** | **3.90** | **8.05** | **$1,568** | 163 | $0 | — |
| **2026** *(OOS)* | same-day *(not live-tradable)* | $9,288 | 1.62 | 2.47 | 3.41 | $4,342 | 129 | $719 | 45/36 |
| | D-1, old params | $8,105 | 1.52 | 2.14 | 3.76 | $3,435 | 127 | **−$464** | 43/38 |
| | **D-1, retuned** | $6,946 | 1.43 | 1.87 | 3.04 | $3,644 | 132 | **−$1,623** | 48/41 |
| | no Swing | **$8,731** | **2.02** | **3.46** | **8.92** | **$1,561** | 87 | $0 | — |

### Risk-clean, no Calm-NKD

| Window | same-day | D-1 old | **D-1 retuned** | no Swing |
|---|---:|---:|---:|---:|
| floor *(in-sample)* | $64,903 | $57,289 | **$54,867** | $39,907 |
| 2025 *(OOS)* | $13,236 | $12,419 | **$6,279** | $8,616 |
| 2026 *(OOS)* | $8,260 | $7,077 | **$5,918** | $7,703 |

*(2025 risk-clean: PF 2.00 → 1.82 → 1.42 → 2.51 · Sharpe 2.96 → 2.63 → 1.84 → 4.27. 2026 risk-clean: PF 1.55 → 1.45 → 1.35 → 1.83 · Sharpe 2.57 → 2.19 → 1.80 → 3.46.)*

---

## 4. What the table says

**The retune made it worse, out-of-sample, on every measure.** Not marginally: in 2025 the retuned sleeve gives up $6,957 against the same-day baseline and $6,141 against its own old params, and it does so while taking *more* trades. That is the signature of a parameter fitted to the floor.

**Swing's own contribution under a causal label is negative in both OOS windows**, under both parameter sets in 2026 and under the retuned set in 2025:

```text
                floor        2025        2026
same-day      +25,677      +4,690        +719      <- not live-tradable
D-1 old       +18,429      +3,906        -464
D-1 retuned   +16,883      -2,190      -1,623
```

**In 2026, removing Swing beats every live-tradable Swing route on every metric** — net, PF, Sharpe, Calmar and drawdown. In 2025 no-Swing gives up $3,804 of net against D-1-old-params and buys PF 3.01 against 2.05, Sharpe 3.90 against 2.50, and a maximum drawdown of $1,568 against $4,915.

The one thing Swing clearly does is carry the in-sample floor: $25,677 of it. That is the window the parameters were chosen on.

---

## 5. Answers

| question | answer |
|---|---|
| Best causal D-1 params found | `ema=10, mult=2.5, max_hold=5` — 4/10 folds, a plurality |
| Baseline reproduced | **Yes**, 30/30, before anything was compared |
| same-day → D-1 old → D-1 retuned → no-Swing (2025) | $16,997 → $16,181 → **$10,040** → $12,377 |
| same-day → D-1 old → D-1 retuned → no-Swing (2026) | $9,288 → $8,105 → **$6,946** → **$8,731** |
| Swing remains enabled | **Yes** — shadow/research, as the operator directed |
| Eligible for paper | **No.** OOS does not support promotion |
| Any live route code changed | **No.** No detector, no params source, no gate |
| `orders_possible` | **False** — `PAPER_SHADOW_EVIDENCE` |

Nothing was promoted, so nothing in step 9 of the brief was done: `SWING_TF_PARAM` is untouched, the live detector still receives the object it always did, and no identity document was rewritten. The same-day result stays where it is, now with two stages of evidence attached saying it is not live-tradable.

---

## 6. What I would not conclude from this

**Not `DROP_SWING`, and the case for it is now materially stronger than it was.** What holds it back is the shape of the evidence, not sentiment:

- Two OOS windows, one of them eight months and 45–48 taken trades. No confidence interval was computed and none of these differences has been tested against noise.
- The grid is nine points in two dimensions. `max_hold_days` was never in it, and neither was the context filter, whose thresholds are still the ones frozen from the floor.
- The selection is unstable under *both* labels — 4/10 with a tie in the control. A protocol that cannot pick stably under the label it was designed for is weak evidence about the other label.

What would settle it: a causal-label selection over a grid that includes the hold cap and the filter, with a day-level bootstrap on the OOS windows, and a pre-committed threshold. That is a stage, not a paragraph.

**And separately: the frozen parameter's provenance needs an owner.** Today Track 1 Swing runs `ema=30, mult=2.5` on the strength of a "5/6 folds" claim that could not be reproduced here under any reading. That is true regardless of what happens to the causal question.

---

## Safety

```text
orders_possible False · blocking ['PAPER_SHADOW_EVIDENCE'] · scheduler pid 3000, not restarted
no broker call · orders dir ABSENT · TRACK1_ORDERS_APPROVED unset · confirmation intact
no live route code changed · SWING_TF_PARAM untouched · no gate opened
baseline promotion artifacts restored byte-identical after every regeneration (sha256 verified)
```

No paper-readiness gate was opened, and none could be: this stage produced experimental WFO output and nothing that any gate reads.
