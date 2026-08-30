# Track 1 — Baseline History

**Route:** `track1_candidate` · **Compiled:** 2026-08-29 · **Status:** shadow only, orders impossible

How Track 1 got to the numbers in
[`TRACK1_BASELINE_INDEX_2026-08-29.md`](TRACK1_BASELINE_INDEX_2026-08-29.md), in the order it
actually happened. The index says *what to quote*; this says *why those and not the others*.

---

## 1. The original Track 1 candidate baseline

Four sleeves on one account: `roska4_calm`, `roska4_stress`, `roska4_swing`, `global_nkd`. Three
windows — a 2018–2024 in-sample floor, a 2025 out-of-sample vault, and a partial 2026 vault
through 2026-08-19 — under two policies, the full stack and a risk-clean variant that drops the
Calm-NKD overlap. Settings fixed at $50,000, one micro, two ticks a side, family cap 5.0%/4.4%,
production fill law.

## 2. Runtime split and Track 1 shadow isolation

Track 1 was given its own runtime rather than sharing the legacy one: its own book
(`live_positions.track1.json`), its own lock, its own max-hold marker, its own client id, and its
own safety jobs. The legacy safety jobs kept draining the old book alongside. This is what makes
"Track 1 is flat" a statement that can be checked independently of the legacy route.

## 3. B1, the account baseline, and legacy retirement

The order gate held on B1 — broker account and legacy retirement — until the operator signed
`track1_go_live_confirmation.json` on 2026-08-27. That record confirms **legacy retirement only**.
It carries no order-approval field of any kind, which is why signing it moved the lead blocker to
`PAPER_SHADOW_EVIDENCE` rather than opening anything.

## 4. Calm timing and the two-phase correction

Calm decides at 09:32 and observes at 10:02. The two halves are separated on purpose: the DECIDE
half must not be shown values the OBSERVE half produces. That contract is why the Calm strategy
panel was left unwired rather than wired wrongly — a panel showing the second half's numbers
against the first half's decision would be a leak dressed as a diagnostic.

## 5. Data observation and dashboard diagnostics

The market view grew from "no signal" to a panel that says *why* there is no signal, using the
sleeve's own rule values. The rule throughout: values are addressed out of the payload, never
re-derived in the frontend, because a second implementation of a decision drifts from the first.

## 6. The Swing same-day problem

This is the hinge of the whole story.

The Swing backtest, the artifact and the regeneration all read the **previous** session's regime
label. The live detector did not — it was handed the raw label map and looked up the session's own
row, a row computed from that session's 16:00 close. At 14:05, that row does not exist.

So the outer gate passed on yesterday's label and the detector immediately refused on a missing
one, **every session, silently**. For eight stages the route said one thing about Swing and did
another, and no recorded row said either.

A same-day baseline is therefore **not a baseline**. Its numbers are real and they are not
attainable, because they need a price that has not happened when the sleeve must decide.

## 7. The D-1 reproduction — old/effective ema=50

Re-measured on the causal previous-day label, the selected identity reproduces from code:
full stack **+$66,796 / +$16,181 / +$8,105**, risk-clean **+$57,289 / +$12,419 / +$7,077**,
artifacts byte-identical across repeated runs.

The name carries its own history. The config *requests* ema=30; the artifact was generated with
**ema=50**. That is why the identity is called "old/effective ema=50" rather than simply "ema=30"
— see §10.

## 8. The retune and the full grid

Two attempts to do better under D-1, both measured, **neither promoted**:

- a narrow retune landing on ema=10;
- a full walk-forward grid whose winner was a different corner again.

Search space and promotion thresholds were stated **before** the out-of-sample numbers were seen,
and the results did not clear them. Nothing from either is a baseline, and quoting one would
publish a parameter the route does not run.

## 9. SPY and ES intraday proxies — rejected

If the previous day's label is stale by 14:05, could an intraday proxy recover the current
regime before the Swing window opens? Two were tried, SPY and ES, both strictly causal, both
forbidden the 16:00 close. Neither was selected. They are research, and the index marks them
`REJECTED_RESEARCH`.

## 10. Stage M — the parameter translation

Why did a config asking for ema=30 produce an ema=50 artifact? Not a bug in the strategy: the
regeneration wrapper contained an unrecorded substitution that rewrote the period when a
particular flag combination was set. The tuning engine and the artifact engine were **not the same
engine**.

This matters more than the number it explains. It is the reason for the standing rule: *do not
report performance from an artifact unless you can prove which parameters generated it.* It also
superseded an earlier apparatus concern that had been attributed to the grid search itself.

## 11. The operator override

With same-day ruled out, the retunes unpromoted and the proxies rejected, the remaining live
choice was D-1 old/effective ema=50 — and on the most recent window its contribution is negative.

The operator included Swing in paper scope anyway, as an explicit **risk acceptance**, recorded in
`track1_swing_paper_override.json`, signed 2026-08-29:

```text
parameter_promotion   false      evidence_promotion   false
risk_acceptance       true       grants_orders        false
```

Accepted **against** four caveats that stay attached to the decision rather than being filed away:
same-day Swing is not live-tradable; Swing's 2026 contribution is negative; the no-Swing variant
is better on risk-adjusted out-of-sample; and no day-level bootstrap has been run.

Then, on 2026-08-29, the live detector was changed to receive the causal D-1 object end to end —
so the sleeve that had refused every session **will now decide**.

## 12. Canonical numbers to quote

**Historical reference — not live-tradable, because same-day Swing:**

| | floor 2018–2024 | 2025 OOS | 2026 OOS (to 08-19) |
|---|---:|---:|---:|
| full stack | +$74,410 | +$16,997 | +$9,288 |
| risk-clean | +$64,903 | +$13,236 | +$8,260 |

**Selected paper baseline — causal D-1 old/effective ema=50:**

| | floor 2018–2024 | 2025 OOS | 2026 OOS (to 08-19) |
|---|---:|---:|---:|
| full stack | +$66,796 | +$16,181 | +$8,105 |
| risk-clean | +$57,289 | +$12,419 | +$7,077 |

**Swing, two figures that are not interchangeable:**

| | floor | 2025 | 2026 |
|---|---:|---:|---:|
| cluster P&L *(accounting split)* | +$18,429 | +$3,906 | −$464 |
| **marginal add vs no-Swing** | **+$17,382** | **+$3,804** | **−$626** |

"What does Swing add?" is answered by the marginal row. On 2026 it is negative on both, and worse
on the one that answers the question.

## 13. What remains before paper activation

**`PAPER_SHADOW_EVIDENCE`** — the only blocker left. It requires five judgeable days with **zero**
failing days and complete Calm decision evidence.

Every day currently in the qualifying window was recorded **before** the Swing fix, so the window
cannot become entirely post-fix until five post-fix trading days have run. The first post-fix
Swing slot is **Monday 2026-08-31, 14:05 ET**.

Also open, and named rather than closed:

- the live signal rows record an empty `params_hash`, which caps a post-fix replay-parity slot at
  `UNKNOWN` until parity joins the full identity from the explanation record;
- the frozen `SWING_TF_PARAM` provenance has still not been reproduced;
- no day-level bootstrap has been run on any out-of-sample comparison.

```text
orders_possible          False
blocking                 ['PAPER_SHADOW_EVIDENCE']
orders dir               ABSENT
TRACK1_ORDERS_APPROVED   unset
```
