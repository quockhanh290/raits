# Stage 5ZZZ-H — the full Track 1 candidate, with Swing reading a causal D-1 label

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

## Decision

# `NEEDS_RETUNE`

Same-day Swing is **not live-tradable** — so the choice is not "same-day or D-1", it is "D-1 or nothing". Under D-1 the sleeve is materially weaker in every window and **turns negative in the most recent out-of-sample one**, but its parameters and its context filter were both selected against a label set that included the session's own close. The sleeve should not enter the paper route as it stands, and dropping it is not established either.

---

## 1. Baseline reproduced

Re-run from the producing script — `scratch/combined_repaired_replay_20260822.py`, named in the handoff doc — **all thirty numbers match** the doc's two tables exactly.

| Window | Policy | Net | PF | Sharpe | Calmar | MaxDD |
|---|---|---:|---:|---:|---:|---:|
| floor | full stack, cap 5.0/4.4 | +$74,410 | 1.67 | 2.12 | 2.14 | $4,973 |
| 2025 | full stack, cap 5.0/4.4 | +$16,997 | 2.26 | 2.76 | 4.45 | $3,901 |
| 2026 | full stack, cap 5.0/4.4 | +$9,288 | 1.62 | 2.47 | 3.41 | $4,342 |
| floor | risk-clean, cap 5.0/4.4 | +$64,903 | 1.62 | 2.34 | 1.92 | $4,845 |
| 2025 | risk-clean, cap 5.0/4.4 | +$13,236 | 2.00 | 2.96 | 3.09 | $4,632 |
| 2026 | risk-clean, cap 5.0/4.4 | +$8,260 | 1.55 | 2.57 | 2.75 | $4,797 |

Confirmed inputs, from each window's own recorded argv rather than from a CLI default:

```text
account            $50,000            family cap      5.0% / 4.4%
contracts          1 micro            slippage        2 ticks per side
sleeves            roska4_swing · roska4_stress · roska4_calm · global_nkd
HMM fit end        floor 2022-12-31 · 2025 2024-12-31 · 2026 2024-12-31   (walk-forward)
window end         floor 2024-12-31 · 2025 2025-12-31 · 2026 2026-08-19
Calm-NKD switch    ON in the full stack, OFF in risk-clean
```

---

## 2. One thing changed

The swing basket's labels object, and only that. The seam is `SwingTFEngine.backtest_basket`, which is the R4 basket's entry and nothing else: NKD runs through `backtest_swing_tf` directly with its own already-lagged object, and Stress is disabled in this regeneration.

Two self-checks had to pass or the run would have been measuring something else:

- **NKD's trade list is byte-identical** in all three windows. Had it moved, the patch reached further than the swing basket and every number below would be void.
- **At least one R4 instrument changed** in all three. Had none changed, a "no difference" result would have been an artefact of a no-op.

Both held, in all three windows, along with identical argv and identical slippage. The baseline artifacts were copied out before each run and restored; their sha256 is unchanged.

---

## 3. Full stack, Calm-NKD ON

| Window | | Net | PF | Sharpe | Calmar | MaxDD | Swing taken/rej |
|---|---|---:|---:|---:|---:|---:|---:|
| floor **(in-sample)** | baseline | +$74,410 | 1.67 | 2.12 | 2.14 | $4,973 | 545/190 |
| | **D-1** | **+$66,796** | 1.59 | 1.91 | 1.92 | $4,973 | 564/197 |
| | delta | **−$7,613 (−10.2%)** | −0.09 | −0.21 | −0.22 | +$0 | +19/+7 |
| 2025 **(OOS)** | baseline | +$16,997 | 2.26 | 2.76 | 4.45 | $3,901 | 55/48 |
| | **D-1** | **+$16,181** | 2.05 | 2.50 | 3.36 | $4,915 | 57/48 |
| | delta | **−$817 (−4.8%)** | −0.20 | −0.26 | −1.09 | +$1,014 | +2/+0 |
| 2026 **(OOS)** | baseline | +$9,288 | 1.62 | 2.47 | 3.41 | $4,342 | 45/36 |
| | **D-1** | **+$8,105** | 1.52 | 2.14 | 3.76 | $3,435 | 43/38 |
| | delta | **−$1,183 (−12.7%)** | −0.10 | −0.33 | **+0.35** | −$907 | −2/+2 |

## 4. Risk-clean, no Calm-NKD

| Window | | Net | PF | Sharpe | Calmar | MaxDD | Swing taken/rej |
|---|---|---:|---:|---:|---:|---:|---:|
| floor **(in-sample)** | baseline | +$64,903 | 1.62 | 2.34 | 1.92 | $4,845 | 545/190 |
| | **D-1** | **+$57,289** | 1.53 | 2.08 | 1.67 | $4,914 | 564/197 |
| | delta | **−$7,613 (−11.7%)** | −0.09 | −0.26 | −0.25 | +$68 | +19/+7 |
| 2025 **(OOS)** | baseline | +$13,236 | 2.00 | 2.96 | 3.09 | $4,632 | 55/48 |
| | **D-1** | **+$12,419** | 1.82 | 2.63 | 2.38 | $5,645 | 57/47 |
| | delta | **−$817 (−6.2%)** | −0.17 | −0.33 | −0.71 | +$1,014 | +2/−1 |
| 2026 **(OOS)** | baseline | +$8,260 | 1.55 | 2.57 | 2.75 | $4,797 | 45/36 |
| | **D-1** | **+$7,077** | 1.45 | 2.19 | 1.93 | $5,853 | 43/38 |
| | delta | **−$1,183 (−14.3%)** | −0.10 | −0.38 | −0.82 | +$1,056 | −2/+2 |

The net delta is the **same dollar figure** under both policies in every window, which is the arithmetic check on the whole exercise: the Calm-NKD switch adds a contribution that this change does not touch.

---

## 5. Sleeve contribution — where the money actually moved

Booked P&L by cluster, after every cap and override:

| Window | | Swing | Stress | Calm | NKD |
|---|---|---:|---:|---:|---:|
| floor | baseline | $25,677 | $26,166 | $9,162 | $13,405 |
| | **D-1** | **$18,429** | $26,166 | $8,797 | $13,405 |
| | delta | **−$7,248** | **$0** | −$365 | **$0** |
| 2025 | baseline | $4,690 | $4,531 | $1,812 | $5,964 |
| | **D-1** | **$3,906** | $4,531 | $1,780 | $5,964 |
| | delta | **−$784** | **$0** | −$32 | **$0** |
| 2026 | baseline | $719 | $831 | $702 | $7,036 |
| | **D-1** | **−$464** | $831 | $702 | $7,036 |
| | delta | **−$1,183** | **$0** | $0 | **$0** |

Stress and NKD move by **exactly zero** in all six cells. Calm moves slightly, and that is real rather than leakage: Calm and Swing interact through same-symbol suppression, so a different swing entry can change which Calm entry survives.

**In 2026 the Swing sleeve turns negative under a causal label: −$464 against +$719.** It is carrying 45 trades over eight months, so this is a small sample and a point estimate — but it is the most recent out-of-sample evidence there is.

---

## 6. Swing specifics

| Window | shared | only same-day | only D-1 | churn | pre-cap P&L delta | post-cap P&L delta |
|---|---:|---:|---:|---:|---:|---:|
| floor | 633 | 119 | 136 | **28.7%** | −$14,137 | −$7,248 |
| 2025 | 71 | 34 | 34 | **48.9%** | **+$1,081** | **−$784** |
| 2026 | 59 | 22 | 22 | **42.7%** | −$3,815 | −$1,183 |

**2025 is the row that justifies the brief's instruction not to judge on standalone numbers.** Before portfolio caps the D-1 sleeve is *better* by $1,081; after the caps and overrides it is *worse* by $784. Reading the sleeve alone would have inverted the sign of the answer.

**Ordering did change.** Same priority rule, different candidate set:

```text
floor   taken +6   rejected +8   family-rejected  0   same-symbol suppressions -8
2025    taken +1   rejected +2   family-rejected +2   same-symbol suppressions -2
2026    taken -2   rejected +2   family-rejected -3   same-symbol suppressions  0
```

`double_booked = 0` in every cell, both variants — the mechanical repairs held.

---

## 7. Why "worse" is the expected direction, and what it does not prove

The same-day label is built from the session's 16:00 close and gates a 14:00–15:55 entry. A rule that reads six hours of the future should look better; the −10% / −5% / −13% is a measurement of **how much the baseline was flattered**, not evidence that D-1 is a bad rule.

What it does not settle: the sleeve's parameters — ema, chandelier multiple, hold cap — **and its R4 context filter thresholds** were all selected under the same-day labels. The D-1 variant here runs new labels through an old filter. That is the fairest single-variable comparison available, and it is also not a fair test of D-1 as a design.

---

## 8. Answers

| question | answer |
|---|---|
| Baseline reproduced | **Yes** — 30/30 numbers from a fresh run of the producing script |
| Full stack: baseline → D-1 | +$74,410 → +$66,796 · +$16,997 → +$16,181 · +$9,288 → +$8,105 |
| Risk-clean: baseline → D-1 | +$64,903 → +$57,289 · +$13,236 → +$12,419 · +$8,260 → +$7,077 |
| Is same-day Swing live-tradable | **No.** The label is computed from the session's close and does not exist during the window |
| Is D-1 Swing worth keeping | **Not established.** Positive in floor and 2025, **negative in 2026** — and untuned |
| Paper route | **Disable Swing**, retune under D-1 before reconsidering |
| `orders_possible` | **False** — `PAPER_SHADOW_EVIDENCE` |

### On "disable"

This changes nothing operationally. Stage 5ZZZ-G measured that live Swing already refuses every session, because the detector looks up a row that does not exist yet. Disabling it makes an existing silence explicit and auditable instead of leaving a sleeve that appears enabled and never fires.

### On "retune"

Re-running the **same** walk-forward selection against causal labels is not curve fitting — the original selection was made on an information set the live route cannot have, so it has to be redone on valid inputs. No parameter values are proposed here, and none should be chosen by looking at the table above.

---

## 9. Caveats

- **floor is in-sample.** It is the largest delta and the weakest evidence.
- **2026 is eight months and 45 taken trades.** No confidence interval was computed; the −$1,183 is a point estimate.
- **The context filter is inherited.** Its thresholds were fit under same-day labels, so this comparison is not a fair test of D-1 as a design.
- **One regeneration per window.** No bootstrap, no sensitivity sweep.
- **A concurrency mistake was made and caught.** The replay was re-run while the regeneration was still overwriting the shared artifact files, and it produced a floor figure of $66,796 for the *baseline*. The baselines' sha256 confirmed the restore, the run was repeated cleanly, and all thirty numbers returned. Recorded because a number that appeared once and vanished is exactly the kind that gets quoted later.

### Safety

```text
orders_possible False · blocking ['PAPER_SHADOW_EVIDENCE'] · scheduler pid 3000, not restarted
no broker call · orders dir ABSENT · TRACK1_ORDERS_APPROVED unset · confirmation intact
runtime evidence untouched · baseline artifacts restored byte-identical (sha256 verified)
```

The only edit to a baseline-producing script is an additive per-cluster P&L accumulator, read by nothing in the control flow. It was proved harmless by re-running the script and matching all thirty baseline numbers again.
