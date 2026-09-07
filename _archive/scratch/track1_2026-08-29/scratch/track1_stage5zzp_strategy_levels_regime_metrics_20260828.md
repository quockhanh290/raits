# Stage 5ZZP — "not published" was never the same as "not computed"

**2026-08-27 → 2026-08-28.** No orders · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` ·
no orders directory · confirmation unchanged · scheduler untouched · no broker call · **no
trading decision moved** (proven below).

---

## Scope, stated up front

This stage asked for strategy diagnostics across four sleeves, HMM metrics, volume, a backend
v2 and a UI v2. **Three of those are delivered in full and proven; the sleeve work is complete
for Stress and deliberately not attempted for the other three.** What was not done is named in
§6 with the reason from source, rather than left looking finished. Nothing is half-wired.

## The finding

Stage 5ZZL read **return types** and concluded that neither the sleeves nor the model published
anything under their verdicts. Reading the **implementations** shows otherwise, and the gap
between those two readings is the whole stage.

| | 5ZZL reported | actually |
|---|---|---|
| Stress rule values | `not_exposed_by_sleeve` | every one computed, compared against a named threshold, then dropped |
| Regime score | `not exposed by model` | `HMMEngine.predict_proba` exists; the posterior is real |
| Volume | absent | present in **every** instrument store, simply not aggregated |
| Regime threshold | `not exposed by model` | **genuinely absent**, and now says why from the mechanism |

## 1. Stress — the values were one frame below the slot that said it had none

`entry_conditions` made four comparisons and returned a bool:

```python
if feats["below_count"]   < p.breadth_min:  return False
if feats["gapdown_count"] < p.gapdown_min:  return False
if feats["wide_count"]    < p.wide_min:     return False
if p.avg_gap_max is not None and feats["avg_gap"] > p.avg_gap_max: return False
```

The values were computed (`peer_features`), the thresholds were named (`StressParams`), and
both sat at the call site. **Only the join between them was thrown away** — while the slot one
frame up wrote `not_exposed_by_sleeve` into its own record.

Two narrow refactors, both single-source:

- `entry_checks()` states the four comparisons **as data**, and `entry_conditions` became
  `all(c["passed"] for c in entry_checks(...))`. Written as a second function beside the
  original it would have been two statements of one rule — the drift this repo has paid for.
- `basket_state()` is `detect_entry_for_slot`'s own opening, extracted. It computed the
  contexts and features and discarded them on the way to `return []`.

### Proof that no decision moved

```text
entry_conditions vs the pre-refactor function
  5,760 combinations × 5 parameter sets          0 mismatch

detect_entry_for_slot on real bars
  652 slot-days, of which 215 carry real setups  0 differences
```

The 215 matters: an all-empty baseline would have proved nothing, and the first 40-day sample
**was** all-empty. The sweep was widened until it contained 97 days on which the basket
genuinely set up.

### What a no-signal Stress slot can now say

Before: `NO SIGNAL`, and nothing behind it.

After, for 2026-08-27:

```text
Instruments below open and VWAP          4  >= 4         passed
Instruments gapped down                  0  >= 3         FAILED
Instruments with a wide range            0  >= 0         passed
Average basket gap                  +0.51%  <= -0.10%    FAILED
```

The basket was fully bearish on breadth and **gapped up half a percent**. That is a market
answer, not a data answer — and an operator no longer goes looking for a feed problem that is
not there.

`basket_state` names three different failures — `missing_bars`, `session_not_judgeable`,
`conditions_not_met` — because "no setup" and "no bars" are not the same fact.

## 2. Regime — a real score, and a threshold that genuinely does not exist

```python
predict_current -> self._model.predict(X)[-1]        a Viterbi decode
predict_proba   -> self._model.predict_proba(X)[-1]  a posterior per state
```

Recorded now, from the same model on the same window:

```text
label     Calm            as of 2026-08-27
score     0.998354        posterior probability of the labelled state
margin    0.996711        over Normal
states    Calm 0.998354 · Normal 0.001643 · Stress 0.000003
agreement Viterbi == argmax          (measured 8/8 recent days, flagged when it is not)
threshold NONE
```

**The absent threshold is a statement about the mechanism, not about reach.** Viterbi picks the
most likely *path*; nothing is compared against a constant, so there is no cut to be near, and
a "distance to threshold" display would describe a decision procedure the model does not use.
What stands in its place is the **lead over the runner-up state** — a real number, named as a
margin, never as a threshold distance. A test reads `raits/hmm/engine.py` and asserts
`predict_current` contains no threshold, so that sentence cannot quietly become wrong.

The 8.54-second reason from 5ZZL still holds: this is **recorded by a probe**, never computed
in a dashboard request. A test pins that `label_regimes` appears nowhere in the reader.

## 3. Volume — it was there all along

```text
MNQ   volume on every bar, mean 3,195
MES   volume on every bar, mean 1,269
MNKD  volume on 270 of the last 500 bars, mean 2.5   — a genuinely thin instrument
```

Summed across each 5-minute bucket and rendered as a pane inside the chart's **existing** box,
so adding it cannot move the panel. `volume_status` has four values, because a column of zeros
and an absent column must not draw the same: `present`, `present_but_zero`, `partial`,
`not_available`. Nothing is synthesised, and a test forbids it.

## 4. Concrete before / after, per sleeve

| sleeve | before | after |
|---|---|---|
| **Stress** | `NO SIGNAL`, no bars volume, `not_exposed_by_sleeve` on every rule | four rule values with thresholds, the first failing one as a chip, volume pane |
| **NKD** | `NO SIGNAL`, no volume | volume pane; rules named `not_computed_until_entry` with the reason |
| **Swing** | `NO SIGNAL`, no volume | volume pane; same honest naming |
| **Calm** | not charted | unchanged — see §6 |

## 5. The dashboard

The regime panel replaced `Score not published` with **`CONFIDENCE 99.8%`**, added
**`LEAD OVER NEXT 99.7% over Normal`**, and keeps **`SHIFT THRESHOLD None published`** with the
Viterbi explanation on hover. The market view gained a volume pane and a chip naming the first
unmet condition. No new panel, no new visual language, and the chart box is unchanged.

## 6. What is NOT done, and why

**NKD and Swing rule diagnostics.** Their detector returns `SwingSetup(entry, stop, daily_atr,
regime)` when a setup exists and `None` when it does not. So entry and stop **are** published
on a signal day, and on a quiet day there is nothing to publish — the entry level is produced
by a per-bar signal function inside a validated core strategy, not by a comparison against a
standing level. Publishing a "distance to entry" would mean forming an entry the detector never
formed. Reported as `not_computed_until_entry` with that sentence.

**Calm.** `entry_conditions` already returns a dict of its own values, so the raw material is
there — but the live path reaches it through the two-phase DECIDE/OBSERVE contract, and the
DECIDE half must not be shown values the OBSERVE half produces. Wiring it without honouring
that split would put a 10:00 reference price on a 09:32 decision. **Left unwired rather than
wired wrongly.**

**Per-slot diagnostic persistence.** The Stress diagnostic is computed by the reader from the
same stores the detector uses, not written into each signal row. Persisting it belongs with a
change to the slot's own write path, which touches the decision path and did not belong in a
stage whose contract was "change no decision".

## 7. Tests

**22** new in `scratch/test_track1_stage5zzp_strategy_levels_regime_metrics_20260828.py`, plus
the corrected claims below. No broker contacted, nothing written to the runtime tree, no
decision touched.

The equivalence tests keep the **pre-refactor function** in the test file as the baseline —
comparing the new code against a re-reading of itself would be true by construction.

### Four claims corrected because this stage disproved them

| claim | now |
|---|---|
| `score is None` | the score is published and in `[0,1]` |
| `Score not published` visible | `CONFIDENCE 99.8%` visible; the **threshold** is the named-absent one |
| tooltip says "publishes labels but not the score" | tooltips say what the numbers are, and why the threshold cannot exist |
| module docstring: "there is no score, no probability" | corrected in place, with the engine calls quoted |

That last one matters: it was a **statement in the source** that had become false, of exactly
the kind this project keeps finding. It was corrected where it lives, not annotated elsewhere.

### Two of my own mistakes

I read `MES has no bars for this session` as a defect. It was 01:56 ET on the **next** session —
the diagnostic was right and my reading of it was wrong; the same three-clock trap this project
warns about. And a DOM assertion was case-sensitive against a CSS-uppercased label, which is
the identical trap 5ZZM hit on the empty-state heading.

### Suites

```text
5ZZP + 5ZZL/M + dashboard backend + realtime contract + realtime DOM
  + ops + 5ZZN + 5ZZO                                    414 passed, 0 failed
```

## 8. Safety, before and after

```text
orders_possible                False -> False
track1_blocking                ['PAPER_SHADOW_EVIDENCE'] -> unchanged
confirmation                   True -> True, untouched
scheduler                      pid 3000, track1-only-shadow, 0 legacy entry jobs, untouched
TRACK1_ORDERS_APPROVED         unset
track1_runtime/orders          ABSENT
broker order calls             0
trading decisions moved        0 — proven over 5,760 rule cases and 652 slot-days
```

Runtime evidence written by this stage: one appended regime-label record. No trading file
touched.
