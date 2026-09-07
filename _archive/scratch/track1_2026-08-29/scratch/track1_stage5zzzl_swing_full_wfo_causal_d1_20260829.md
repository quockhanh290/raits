# Stage 5ZZZ-L — the full WFO grid for Swing under causal D-1

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

## Decision

# `KEEP_RESEARCH_ONLY`

The wider grid did its job — it found a **more stable optimum the old grid could not reach**: `ema=50, chandelier=2.0, hold=5`, selected in **5 of 10 folds**, against Stage 5ZZZ-I's 4 of 10 with a tie.

It cannot be promoted, and the reason is not the parameter. **The apparatus that converts a parameter choice into full-stack numbers cannot be shown to honour that parameter**, so the OOS evidence the promotion bar requires cannot be produced honestly. That has to be fixed before any parameter-based promotion is possible — and it casts doubt backwards on Stage 5ZZZ-I's retuned arm.

---

## 1. Two findings about the measurement chain, before any result

### 1a. The tuning and the artifact used different engines

`SwingTFEngine.backtest` imports **`futures._validated_core.backtest_swing_tf`**, and that is what generates the promotion artifacts the full-stack replay consumes. `pooled_swing_wfo.py` — which the repo credits for the frozen parameters — and Stage 5ZZZ-I's retune both used **`futures.swing_tf_harness.backtest_swing_tf`**. Different objects, and measured on identical inputs, different behaviour:

```text
MES, floor, D-1 labels
  ema=30 mult=2.5 hold=5   _validated_core 555 trades $ 7,855.72   harness 564 $10,015.76   +$2,160
  ema=10 mult=2.5 hold=5   _validated_core 556 trades $13,269.01   harness 563 $14,742.88   +$1,474
  ema=50 mult=3.0 hold=5   _validated_core 503 trades $ 5,854.15   harness 509 $ 6,811.41   +$  957
```

**This stage tuned on `_validated_core`** — the engine that actually makes the artifacts. It also probably explains why Stage 5ZZZ-I could not reproduce the frozen `ema30/mult2.5` provenance: the original tuning ran on the research engine too.

### 1b. The artifact regeneration does not reflect the parameter it is given

This is the blocking one, and it was caught by a hash rather than by reading.

The override was moved onto `SwingTFEngine.backtest` — the method that reads the parameters — and the run now **records what the engine was handed**. It reported `(50, 2.0, 5)`. The artifact it produced was nevertheless **byte-identical to the nominal `ema=30, mult=2.5` run**, on the **seven-year floor window**:

```text
floor artifact sha256 (first 16)
  d1     ema=30 mult=2.5   2474723814ae3e92
  d1f    ema=50 mult=2.0   2474723814ae3e92   <- identical, over 7 years and ~190 trades/instrument
  d1r    ema=10 mult=2.5   c504a83b82c57de9   <- different

vault2026
  d1     ema=30 mult=2.5   1ee198a9f10387c8
  ema=50 mult=2.0          1ee198a9f10387c8   identical
  ema=50 mult=2.5          1ee198a9f10387c8   identical
  ema=20 mult=2.5          ef3ef40d10f36315   different
  ema=10 mult=2.5          b878f9fd39cb7171   different
```

So ema **30 and 50 produce the same artifact**; ema **10 and 20 produce different ones**. Over eight months that could be coincidence. Over seven years it cannot be.

The regeneration installs its own engine — `patched_engine(Cfg(..., ema=50, stop_basis=2.0))` — and whatever the interaction is between that configuration and the requested parameters, **it is not the simple pass-through the previous two stages assumed.** I could not resolve the mechanism within this stage, and I am not going to report full-stack numbers produced by a path I cannot show is doing what it is told.

**Consequence for Stage 5ZZZ-I.** Its "D-1 retuned (ema=10)" arm did change the artifact, so *something* moved — but it can no longer be asserted that it was cleanly "ema=10 with everything else held". That stage's conclusion (the retune underperformed) should be treated as **provisional** until this is fixed.

---

## 2. The pre-committed design

Written to `scratch/track1_stage5zzzl_precommit_20260829.md` **before any out-of-sample number existed**.

### The exact grid

| parameter | searched | values |
|---|---|---|
| `ema_period` | **yes** | **{10, 20, 30, 50}** |
| `chandelier_atr_mult` | **yes** | **{2.0, 2.5, 3.0, 3.5}** |
| `max_hold_days` | **yes** | **{3, 5, 10}** |
| `vol_feature` | **yes** | `rvol_slot20`, `rvol_prevbar` — both buckets already exist in every artifact, so this is a swap not a regeneration |
| `range_max`, `rel_volume_max` | planned second pass | **not reached** — blocked by §1b |
| `stop_basis_atr_mult`, `spy_short_filter` | **no** | they belong to `track1_normal_r4`'s own replay, which is not the path that makes these artifacts |
| fill law, `ratchet`, `arm_hours` | **no** | fixed by the brief / not reached by this engine |

**48 engine combinations**, against Stage 5ZZZ-I's 9. `ema=50` is included because it is `NormalR4Params`' own default and was absent from the original grid; `mult=2.0` because the original grid started at 2.5.

### Protocol

```text
labels     RegimeLabels(lag_days=1) - causal D-1; the session's own close is never read
objective  Calmar on the TRAIN fold, minimum 10 basket trades
folds      rolling 18 months train -> 6 months test, stepping 6 months
pooling    one shared parameter per fold across the whole basket
region     FLOOR ONLY - 2025 and 2026 were not read during selection
engine     futures._validated_core.backtest_swing_tf
```

### Thresholds, committed in advance

T1 net ≥ D-1 old in ≥3 of 4 OOS cells and behind by >$500 in none · T2 Swing contribution ≥ $0 in **both** OOS windows · T3 full-stack Calmar ≥ no-Swing in ≥1 OOS window and ≥60% in both · T4 MaxDD ≤115% of D-1 old · T5 winner wins **≥50%** of folds.

---

## 3. What the WFO selected

**48 candidates, 10 folds, floor only.**

| parameters | folds won |
|---|---:|
| **ema=50, mult=2.0, hold=5** | **5 / 10 (50%)** |
| ema=10, mult=2.0, hold=3 | 2 / 10 |
| ema=10, mult=2.5, hold=10 | 2 / 10 |
| ema=50, mult=2.0, hold=3 | 1 / 10 |

```text
2019-07 -> 2020-01   ema=50 mult=2.0 hold=5    102t  $   355   Calmar  3.74
2020-01 -> 2020-07   ema=50 mult=2.0 hold=5    175t  $10,294   Calmar 24.15
2020-07 -> 2021-01   ema=50 mult=2.0 hold=5    192t  $ 6,326   Calmar 13.25
2021-01 -> 2021-07   ema=50 mult=2.0 hold=5    154t  $ 2,311   Calmar  4.21
2021-07 -> 2022-01   ema=50 mult=2.0 hold=5    101t  $ 3,940   Calmar  5.90
2022-01 -> 2022-07   ema=10 mult=2.0 hold=3    335t  $ 8,782   Calmar  7.40
2022-07 -> 2023-01   ema=10 mult=2.0 hold=3    352t  $   733   Calmar  0.28
2023-01 -> 2023-07   ema=10 mult=2.5 hold=10   184t  $ 3,676   Calmar  3.30
2023-07 -> 2024-01   ema=10 mult=2.5 hold=10   103t  $ 5,694   Calmar  8.64
2024-01 -> 2024-07   ema=50 mult=2.0 hold=3     90t  $ 4,020   Calmar 25.05
```

**T5 is met** — 50%, and it is the first five folds consecutively rather than a scattered plurality. Every winning combination uses `mult` ∈ {2.0, 2.5} and eight of ten use `mult=2.0`, which the old grid did not contain at all. That is a real finding about the search space: **the previous grid's floor of 2.5 excluded the region the objective actually prefers.**

**T1–T4 could not be evaluated**, because they require full-stack OOS numbers and §1b blocks producing them faithfully.

---

## 4. What was measurable

Only the `vol_feature` arm could be produced without a parameter override — it is a swap of trade tables that already exist inside each artifact, so it is not affected by §1b.

Full stack, Calm-NKD ON. `same-day` is a reference only and is **not live-tradable**.

| Window | Route | Net | PF | Sharpe | Calmar | MaxDD | Swing $ | Swing taken/rej |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **floor** *(in-sample)* | same-day *(reference)* | $74,410 | 1.67 | 2.12 | 2.14 | $4,973 | +$25,677 | 545/190 |
| | D-1 old | $66,796 | 1.59 | 1.91 | 1.92 | $4,973 | +$18,429 | 564/197 |
| | D-1 narrow retune *(provisional)* | $64,374 | 1.55 | 1.83 | 1.78 | $5,186 | +$16,883 | 580/211 |
| | **D-1 + prevbar vol filter** | $64,477 | 1.55 | 1.81 | 1.65 | $5,601 | +$16,225 | 587/201 |
| | no Swing | $49,414 | **1.82** | **2.19** | 1.84 | **$3,842** | $0 | — |
| **2025** *(OOS)* | same-day *(reference)* | $16,997 | 2.26 | 2.76 | 4.45 | $3,901 | +$4,690 | 55/48 |
| | D-1 old | $16,181 | 2.05 | 2.50 | 3.36 | $4,915 | +$3,906 | 57/48 |
| | D-1 narrow retune | $10,040 | 1.66 | 2.16 | 2.52 | $4,065 | −$2,190 | 62/42 |
| | **D-1 + prevbar** | **$17,758** | 2.19 | 2.91 | 5.32 | **$3,402** | **+$5,483** | 59/48 |
| | no Swing | $12,377 | **3.01** | **3.90** | **8.05** | **$1,568** | $0 | — |
| **2026** *(OOS)* | same-day *(reference)* | $9,288 | 1.62 | 2.47 | 3.41 | $4,342 | +$719 | 45/36 |
| | D-1 old | $8,105 | 1.52 | 2.14 | 3.76 | $3,435 | −$464 | 43/38 |
| | D-1 narrow retune | $6,946 | 1.43 | 1.87 | 3.04 | $3,644 | −$1,623 | 48/41 |
| | **D-1 + prevbar** | $6,918 | 1.42 | 1.81 | 3.02 | $3,651 | −$1,652 | 43/40 |
| | no Swing | **$8,731** | **2.02** | **3.46** | **8.92** | **$1,561** | $0 | — |

Risk-clean floor: $64,903 · $57,289 · $54,867 · **$54,970** · $39,907.

**The prevbar filter is the only arm that has ever beaten the same-day reference out-of-sample** — $17,758 against $16,997 in 2025, with Swing contributing $5,483 and a *smaller* drawdown than D-1 old. And it is worse than D-1 old in 2026, and worse than no-Swing there on every risk metric. One good window and one bad one, which is the same instability every previous arm has shown.

---

## 5. Answers

| question | answer |
|---|---|
| Exact grid | ema {10,20,30,50} × mult {2.0,2.5,3.0,3.5} × hold {3,5,10} = **48**, plus `vol_feature` {slot20, prevbar} |
| Baseline controls reproduced | **Yes** — the 30/30 baseline reproduction from Stage 5ZZZ-H still holds; all control arms are unchanged |
| Selected params | **ema=50, chandelier=2.0, hold=5** |
| Stability | **5/10 folds (50%)**, five consecutive — meets the pre-committed T5, better than 5ZZZ-I's 4/10 |
| Full-stack result for that winner | **Could not be produced faithfully** — see §1b |
| vs D-1 old | not measurable for the winner; the prevbar arm beats it in 2025 (+$1,577) and loses in 2026 (−$1,187) |
| vs no-Swing | no live-tradable Swing arm beats no-Swing in 2026 on any metric |
| Recommended paper treatment | **Keep Swing in shadow/research. Do not make it paper-orderable.** |
| `orders_possible` | **False** — `PAPER_SHADOW_EVIDENCE` |

---

## 6. What has to happen before this question can be settled

The parameter question is now blocked on tooling, not on evidence:

1. **Establish why the regeneration ignores `ema=50` and `ema=30` alike while responding to 10 and 20.** Until that is understood, no parameter-based promotion — and no parameter-based *rejection* — is trustworthy.
2. **Re-run Stage 5ZZZ-I's retuned arm** once it is fixed. Its conclusion is provisional.
3. **Then** evaluate `ema=50 / mult=2.0 / hold=5` against T1–T4, and run the `range_max` / `rel_volume_max` second pass that this stage could not reach.
4. A day-level bootstrap on the OOS windows was **not** run; with 43–62 Swing trades per OOS window, none of the differences above has been tested against noise.

## Safety

```text
orders_possible False · blocking ['PAPER_SHADOW_EVIDENCE'] · scheduler pid 3000, not restarted
no broker call · orders dir ABSENT · TRACK1_ORDERS_APPROVED unset · confirmation intact
no live route code changed · SWING_TF_PARAM untouched · no gate opened
baseline promotion artifacts restored byte-identical after every regeneration (sha256 verified)
```
