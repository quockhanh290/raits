# Stage 5ZZZ-L — pre-commitment

**Written before any out-of-sample number was produced.** 2026-08-29.

---

## 0. A correction that changes the design

`SwingTFEngine.backtest` imports **`futures._validated_core.backtest_swing_tf`**, and that is the
function that generates the promotion artifacts the full-stack replay consumes.

`pooled_swing_wfo.py` — the script the repo credits for the frozen parameters — and Stage 5ZZZ-I's
retune both used **`futures.swing_tf_harness.backtest_swing_tf`**. These are different objects, and
measured on identical inputs they are different behaviour:

```text
MES, floor, D-1 labels
  ema=30 mult=2.5 hold=5   _validated_core 555 trades $ 7,855.72   harness 564 $10,015.76   +$2,160
  ema=10 mult=2.5 hold=5   _validated_core 556 trades $13,269.01   harness 563 $14,742.88   +$1,474
  ema=50 mult=3.0 hold=5   _validated_core 503 trades $ 5,854.15   harness 509 $ 6,811.41   +$  957
```

Two consequences, both stated before anything is run:

1. **This stage tunes on `_validated_core.backtest_swing_tf`** — the engine that actually produces
   the artifacts. Tuning on the other one selects for a strategy the pipeline does not run.
2. **Stage 5ZZZ-I selected its parameters on the other engine**, so its "narrow retune" result is
   weaker evidence than it appeared. It is retained below as a control, and the mismatch is
   probably also part of why Stage 5ZZZ-I could not reproduce the frozen `ema30/mult2.5`
   provenance — the original tuning ran on the research engine too.

---

## 1. The exact grid

Only parameters that reach the artifact pipeline are searched. `NormalR4Params` carries a wider
surface, and the rest of it is deliberately **not** swept, with reasons:

| parameter | searched | values |
|---|---|---|
| `ema_period` | **yes** | **{10, 20, 30, 50}** |
| `chandelier_atr_mult` | **yes** | **{2.0, 2.5, 3.0, 3.5}** |
| `max_hold_days` | **yes** | **{3, 5, 10}** |
| `vol_feature` | **yes, free** | `rvol_slot20` and `rvol_prevbar` — both buckets already exist in every artifact |
| `range_max` | second pass, finalist only | {0.75×, 1.0×, 1.5×} of `FLOOR_RANGE_P90` |
| `rel_volume_max` | second pass, finalist only | {1.5, 2.0, 3.0} |
| `stop_basis_atr_mult` | **no** | belongs to `track1_normal_r4`'s own replay, which is **not** the path that generates these artifacts — sweeping it would change nothing measured here |
| `spy_short_filter` | **no** | same reason: `backtest_swing_tf` takes no `short_days` |
| `gap_fill` / fill law | **no** | the brief fixes production fill law |
| `ratchet`, `arm_hours` | **no** | not reached by this engine |

**Engine grid: 4 × 4 × 3 = 48 combinations**, against Stage 5ZZZ-I's 9. `ema_period = 50` is
included because it is `NormalR4Params`' own default and was absent from the original grid.

## 2. WFO protocol

Unchanged from the process the repo credits, except the engine and the labels:

```text
labels     RegimeLabels(lag_days=1) - causal D-1, no same-day close anywhere
objective  Calmar on the TRAIN fold, minimum 10 basket trades
folds      rolling 18 months train -> 6 months test, stepping 6 months
pooling    one shared parameter per fold across the whole basket
region     FLOOR ONLY. 2025 and 2026 are not read during selection.
engine     futures._validated_core.backtest_swing_tf
```

## 3. Promotion thresholds — committed now

The winner is promoted only if **all five** hold. Stated numerically so that a near-miss cannot be
argued into a pass after the fact.

- **T1 — beats D-1 old out-of-sample.** Net ≥ D-1 old in at least 3 of the 4 OOS cells
  (2025/2026 × full-stack/risk-clean), and behind by more than $500 in none.
- **T2 — the sleeve pays for itself.** Swing's own booked contribution ≥ $0 in **both** OOS windows.
- **T3 — risk-adjusted, against deleting it.** Full-stack Calmar ≥ the no-Swing route's in at
  least one OOS window, and ≥ 60% of it in both.
- **T4 — drawdown.** MaxDD no more than 15% worse than D-1 old in either OOS window.
- **T5 — fold stability.** The selected pair wins **≥ 50%** of folds. Stage 5ZZZ-I's 4/10 was
  called unstable, so the bar is strictly above it.

If T1–T5 all hold → `PROMOTE_CAUSAL_SWING`.
If the grid's best is live-tradable and beats D-1 old but misses the risk bars → `KEEP_D1_OLD_FOR_PAPER`.
If it fails T1 or T2 → `KEEP_RESEARCH_ONLY` or `DROP_FROM_PAPER_ROUTE`, decided on whether the
no-Swing route dominates it out-of-sample on both net and risk.

## 4. Causality

Every candidate uses `RegimeLabels(lag_days=1)`. The session's own daily label — which is computed
from that session's 16:00 close — is never read by any candidate. The same-day arm exists in the
comparison table as a **reference only** and is not eligible for promotion.

## 5. Controls, all already measured

| control | status |
|---|---|
| same-day old params | reference only, **not live-tradable** |
| D-1 old params | measured, Stage 5ZZZ-H |
| D-1 narrow retune | measured, Stage 5ZZZ-I — now known to be tuned on the other engine |
| no-Swing | measured, Stage 5ZZZ-I |
