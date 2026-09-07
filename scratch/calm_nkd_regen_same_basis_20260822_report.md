# Calm-NKD Regenerated on the Current Sleeve's Basis — 2026-08-22

Scratch-only. No production file changed.

This is the "upside path" from the handoff: put Calm-NKD back onto the same data basis and the
same true stop-at-entry risk as the current NKD sleeve, then see whether the switch is still
worth keeping.

**Result: it fails.** Not by a margin — by sign, in-sample, across every parameter tried.

---

## The anchor, and what it took to pass it

Before any challenger number is read, the same harness is run with the **current** sleeve's regime
labels and must reproduce the MNKD book already sitting in the promotion artifact.

| Window | artifact | regenerated | exact match on every price, reason and P&L |
|---|---|---|---|
| floor | 228 trades / $3,898.30 | 228 / $3,898.30 | **yes** |
| 2025 | 31 / $2,203.04 | 31 / $2,203.04 | **yes** |
| 2026 | 26 / $4,292.17 | 26 / $4,292.17 | **yes** |

It failed twice before it passed, and both failures were informative. Getting onto the artifact's
basis required **four** settings, not the two the plan named:

1. the frozen NKD file named in that window's own arguments, not the continuous file;
2. `ema = 10`, `chandelier_atr_mult = 2.5` — the sleeve's own defaults, never overridden;
3. **every bar treated as gap-eligible**, so a stop the market opened beyond fills at that bar's
   open rather than at the stop;
4. **`allowed_regimes` forced to `["Normal"]`** and the **SPY short gate** (short only when the
   previous SPY close is below its 50-day average).

Items 3 and 4 are applied *globally* by the artifact generator. They read as Ro-4 concerns, and
nothing in the sleeve's own configuration mentions them, but they reach every sleeve including
NKD. Without them the regenerated book was 250 trades and $1,823 instead of 228 and $3,898 — close
enough to look plausible, wrong enough to invalidate everything downstream. That is what the
anchor gate is for.

---

## The parameter grid is smaller than it looked

`chandelier_atr_mult` does **nothing** on this basis. With the stop coming from `stop_basis` and
the ratchet switched off, the multiplier drives neither the initial stop nor any trailing. Measured
rather than reasoned: mult 2.0, 2.5 and 3.0 produce **byte-identical trade lists** in all three
windows.

So the original six-variant grid `(ema × mult)` collapses to **ema alone**, and three of those six
variants were the same run.

---

## Calm-NKD with true stop-at-entry risk

Stop distance verified at exactly **2.0 × daily ATR** from entry on every stop exit — so the risk
model the cluster cap charges is now the real stop risk. That half of the ask succeeded.

| ema | floor 2018-2024 | 2025 | 2026 sanity |
|---:|---:|---:|---:|
| 5 | **−$509** | +$2,556 | +$3,399 |
| 10 | **−$3,556** | +$2,778 | +$1,765 |
| 15 | **−$1,545** | +$2,948 | +$1,330 |
| 20 | **−$1,963** | +$3,416 | +$266 |

**Every ema loses money in-sample.** At the sleeve's own ema of 10: 205 trades, PF 0.85, win rate
45.9%, net −$3,556.

Year by year on floor at ema 10:

| 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
|---:|---:|---:|---:|---:|---:|---:|
| −$381 | −$1,121 | −$403 | −$1,979 | −$294 | **+$1,153** | −$532 |

**One positive year out of seven.**

I did not pre-register a numeric threshold before running this, so I will not invent one now. The
result does not turn on where a threshold would have sat: the sign is negative in-sample for every
parameter value, and six of seven years are negative.

---

## Where the old +$7,156 actually came from

The two sleeves are **complementary, not overlapping** — that part of the design was sound. Measured
on the floor window: the current sleeve takes 228 entries, every one on a day whose previous SPY
label was Normal; Calm-NKD takes 205 entries, every one on a day labelled Calm. The intersection is
**zero**. The switch really was adding days the current sleeve sits out.

But the edge on those days was never the Calm gate. It was the stop mechanism. The original variant
ran a 2.5 × **five-minute** ATR ratcheting chandelier: a median stop 23 index points wide — 4.6
ticks, $11.52 — which stopped out 87% of trades at roughly the cost of the round turn and let the
remaining 13% run. Put the same Calm gate on the sleeve's real stop, a fixed 2.0 × daily ATR armed
the next session, and the win rate goes 12.9% → 45.9% and the floor net goes +$7,156 → −$3,556.

The 2025 and 2026 windows are positive, on 27 and 16 trades. Reading that as an edge that "shows up
out of sample" after seven losing in-sample years is the wrong way round.

---

## Correction to the stop/risk audit — the gap-through finding

My audit reported that the harness's stop-fill correction was switched off when the artifacts were
generated, that a funnel found zero candidates for it, and therefore that **"the gap-through fix is
a no-op on this trade set."** That conclusion was wrong, and the way it was wrong matters.

The post-hoc correction was off because a **stronger implementation of the same law was already on**,
one layer down: the artifact generator marks every bar gap-eligible, so any stop the market opened
beyond is relabelled a gap exit and filled at that bar's open. My check scanned stop exits asking
"did this bar already open through the stop" — and every such case had *already been converted* to a
gap exit before my scan saw it. **The check could not have gone red.** It was vacuous by
construction, and I printed its funnel as evidence that the zero was real.

The substantive direction reverses: the artifacts are **more** conservative on stop fills than the
production engine, which only fills at the open when a real time break of more than fifteen minutes
precedes the bar. Measured on the NKD sleeve by running the anchored configuration both ways:

| Window | artifact law (all bars gappable) | production law (>15-min break only) | difference |
|---|---|---|---:|
| floor | 228 trades, $3,898.30, 21 stop / 4 gap exits | 228, $3,903.66, 25 stop / 0 gap | **−$5.36** |
| 2025 | 31, $2,203.04, 3 stop / 0 gap | 31, $2,203.04, 3 / 0 | **$0.00** |
| 2026 | 26, $4,292.17, 1 stop / 1 gap | 26, $4,295.38, 2 / 0 | **−$3.21** |

So the finding that mattered — *no stop in the candidate book is filled at a price the market had
already passed* — still stands. But it stands because the conservative law was applied, not because
the situation never arises. The Ro-4 side carries one gap exit on floor and one in 2026; I have not
priced those separately, which would need a full re-run of the four-instrument sleeve.

---

## Verdict

The regeneration was executed as specified and the anchor passed, so this is a real answer rather
than a failed experiment: **the Calm-NKD switch does not survive being put on the same basis as the
rest of the book.** Its risk model can be fixed — the stop is now a true 2.0 × daily ATR stop-at-entry
and the cap would charge the real number — but once it is fixed there is no edge left to cap.

Per the rule stated before this was run: **fail → close Track 2 and commit to the fallback.**

```text
Normal-R4 filtered qty 1
Stress-MNQ mnq_only_g3_q7 qty 7, cap 10%
Current NKD/MNKD qty 1, cap 6%          (no Calm-NKD switch)
Calm A PCLoc MES/MNQ, ATR15 disaster stop, true stop-risk
Bidirectional same-symbol skip; Stress force-closes same-symbol Calm A
Normal+Calm family cap 5.0% gross / 4.4% net
```

| Window | Net | PF | Sharpe | Calmar | MaxDD |
|---|---:|---:|---:|---:|---:|
| floor 2018-2024 | +$64,903 | 1.62 | 2.34 | 1.92 | $4,845 |
| 2025 | +$13,236 | 2.00 | 2.96 | 3.09 | $4,632 |
| 2026 sanity | +$8,260 | 1.55 | 2.57 | 2.75 | $4,797 |

Two things this does **not** clear, both from the audit and both untouched by the repair: the
max-hold exit still pre-empts the armed stop (four cases on floor, −$424, conservative direction),
and production arms stops at 14:00 while the artifacts assume 14:05. Neither is large; both sit
below the replay, in the engine and in the captured artifacts.

## Artifacts

- `scratch/calm_nkd_regen_same_basis_20260822.py` / `.json` — the regeneration, the anchor gate,
  the inert-multiplier probe, and the ema line
