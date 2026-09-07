# Verification addendum — Stress audit response of 2026-08-21

Scratch-only. Nothing in production was touched. This checks the response pass rather than
accepting it; agreeing is also a conclusion and needs its own measurement.

Script: `scratch/stress_audit_verify_response.py` → `scratch/stress_audit_verify_response.txt`.
It deliberately uses a different code path from the response: my own `lag1` (previous
available label, not `shift(1)`) and `StressLiquidation1020Engine.backtest_basket` directly
rather than `build_variant`.

## Verified — three independent implementations agree

| quantity | my first pass | response pass | this verification |
|---|---:|---:|---:|
| floor lag-1 `breadth3_mnq_mes` | 78 trades, +$776 | 78 trades, +$776 | **78 trades, +$776** |
| floor lag-0 `breadth3_mnq_mes` | 84 trades, +$2,749 | 84, +$2,749 | **84, +$2,749** |

S1, S5, S4.1 and the fill/timing acquittal all reproduce. The 2026 result is real and its
mechanism is confirmed: **2026-04-07 is labelled Normal by the same-day HMM and Stress by the
lag-1 label**, because the preceding session was Stress. Both legs entered and both were
stopped — MES −$176, MNQ −$358. This is worth stating explicitly: lag-1 is not a haircut on
the same trades, it changes *which days trade*. In the floor window 14 Stress days appear only
under lag-1 and 14 only under lag-0.

## Two places where the response's own numbers say more than its summary

### V1 — The lag-1 WFO does not merely look "weak". It is negative without one fold, and the converged pick loses at the end of the sample.

Reading the nine folds in the response report:

| measure | value |
|---|---|
| held-out total | +$573 (report: $571, rounding) |
| largest fold E009 | **+$1,422 = 248% of the total** |
| total excluding E009 | **−$849** |
| folds with zero trades | E013, E016 — 2 of the 9 |
| record among folds that actually traded | 4 positive / 3 negative |
| cumulative path | peaks at +$1,585 after E010, then declines to +$573 |
| final four folds, all picking `wide3_mnq_mes` | **−$1,012** |

This fails the pre-commitment written into `scratch/harness.py`: *"khong nam nao dong gop qua
mot nua tong"* — no single period may contribute more than half the total. E009 contributes
248%. A threshold committed in advance does not get loosened afterwards.

It also cuts against the doc's proposed next step. `TF_REGIME_RESEARCH_2026-08-20.md` step 2
proposes freezing "a new causal selection rule, likely centered on `wide3_mnq_mes`" — but
`wide3` is precisely the variant the procedure converges on from E010 onward, and it returns
−$444, $0, −$568, $0 across the last four held-out folds. The table cited as the reason to
centre on wide3 is the table showing wide3 deteriorating out of sample.

**Correction to my own earlier recommendation.** In the first audit I wrote that `wide3_mnq_mes`
outranks the primary on causality, on the strength of its aggregate lag-1 floor and 2025
figures. That still holds in aggregate, but it does not survive the fold view: on held-out
clusters wide3's record ends negative. My earlier framing was too favourable and should not be
used to justify centring the next selection rule on it.

### V2 — The S2 "PnL is less damning" reading is a netting artifact, not a reduction in risk

The response reports `opposite_pnl = −$48` for floor breadth3 and concludes the overlap P&L
concentration is "less damning". Measured on the gross basis:

| variant | conflicted legs | distinct conflict **days** | net on conflicted | **gross on conflicted** |
|---|---:|---:|---:|---:|
| floor breadth3 | 34/78 (44%) | **24** | −$48 | **$5,486** |
| floor wide3 | 27/57 (47%) | **18** | +$23 | **$4,703** |

−$48 across 34 legs means the legs cancel each other, not that they are small. The operational
exposure is per-event and unchanged: 24 separate days on which a swing LONG and a Stress SHORT
would coexist on the same contract, each one capable of producing the net-zero broker reading
that raises B3 MISMATCH and halts **all** entries system-wide.

So the correct statement is narrower than "less damning": the *P&L attribution* argument for S2
is gone — my original "59% of net" figure was a lag-0 number and is now moot — while the
*operational* case for S2 is exactly as strong as before. The response's own conclusion
("operational blocker vẫn thật", overlap must be blocked before paper) is right; only the
softening clause around it should go.

## Agreed without qualification

- S1 confirmed, magnitude confirmed, mechanism confirmed.
- S3 confirmed: the old WFO never supported the primary, and the lag-1 WFO does not either
  (`breadth3_mnq_mes` selected 0 times in both).
- S5 confirmed: true stop risk 1.0%–1.7% of a $50k account per day; the 7.5%–10% narrative was
  an ATR-basis artifact and is correctly dropped.
- S4.1 confirmed by direct probe: 10:15 cut yields 0 signals, 10:20 cut reproduces the full
  leg count (floor 41 days / 78 legs — identical to the lag-1 backtest, which is a real
  reconciliation, not just a plausibility check).
- Fill/timing stays clean after the label repair.
- Verdict "research hedge only, not paper-ready" — agreed.

## What this changes about the next step

The doc's step 1 ("decide whether to continue Stress at all under lag-1 labels") is the live
question, and V1 pushes the answer toward no. On causal labels the sleeve shows: a floor of
+$776 at PF 1.14, a held-out WFO that is −$849 without its single best cluster, a converged
pick that loses across the final four folds, and 2026 negative on its only two trades. The one
strong window left is 2025, which is a single six-week episode.

If Stress continues, the honest gate is not "freeze a rule centred on wide3" but: state in
advance what the lag-1 event WFO must show — including a concentration limit that E009 would
have failed — and stop if it does not show it.
