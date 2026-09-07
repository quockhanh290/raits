# Combined Candidate — Stop / Risk Audit — 2026-08-22

Scratch-only. No production file was read for modification and none was changed. Everything
below comes from the production engine code, the captured trade artifacts, and the frozen /
live price parquets. Where a number could not be produced, this report says so rather than
estimating.

## How this was measured, and the gate it had to pass first

The four sleeves are stitched together by a replay harness that lives in scratch. To
instrument it — to see every cashflow and every position that is open at the same instant as
another — the replay had to be rebuilt. A rebuilt replay is worth nothing until it reproduces
a number somebody else already published, so the audit refuses to print anything until it
rebuilds two published rows to the dollar:

| check | rebuilt | published |
|---|---:|---:|
| floor, Normal-R4 alone, net | $29,046 | $29,046 |
| floor, Normal-R4 alone, worst drawdown | $6,209 | $6,209 |
| floor, full combined book at Calm cap 5%, net | $72,732 | $72,732 |
| floor, full combined book at Calm cap 5%, worst drawdown | $4,923 | $4,923 |
| every booked cashflow, summed | $72,731.87 | daily series $72,731.87 |

All green in all three windows. Two further checks that a wrong harness would fail: the trade
list is non-empty, and the Calm sleeve actually places trades. Both green.

Two independent reproductions also landed on the existing disaster-stop table: the standalone
Calm A result with no stop ($9,718 floor) and with the 1.5×ATR stop ($9,686 floor) both match
the published rows.

---

## 1. Does each sleeve have a stop, when does it arm, and can it be enforced

| Sleeve | Stop | Armed | Verified how | Verdict |
|---|---|---|---|---|
| Normal-R4 | Explicit, fixed, entry ± 2.0 × daily ATR, never trailed | 14:05 ET the next session | Every one of the 81 chandelier stop exits on the floor window sits within 0.01% of exactly 2.0 × daily ATR from entry — 81/81 | Real stop |
| Current NKD / MNKD | Same construction, entry ± 2.0 × daily ATR, fixed | 14:05 Tokyo the next session | 21/21 stop exits on floor land at exactly 2.0 × daily ATR | Real stop |
| Stress-MNQ | Explicit, setup high × 1.001, same session | Immediately, intraday | Stop price is carried on every trade row and is what the exit routine tests | Real stop |
| Calm-NKD challenger | Engine-default trailing chandelier on **5-minute** ATR, **not** the 2.0 × daily-ATR fixed stop the rest of the book uses | The frame's session boundary — no live arming model at all | Median realised stop distance is 23 index points on the floor window, i.e. **4.6 ticks**, $11.52 | Stop exists but is not the same mechanism, and is not live-shaped — see §4 |
| Calm A, as carried in the combined replay | **None.** Time exit at 15:55 only | — | The replay's own header says the cap is an ATR proxy | No stop |
| Calm A with the 1.5 × daily ATR disaster stop | Explicit, entry − 1.5 × daily ATR | Immediately, intraday | Stop price carried per trade; cap uses it | Real stop, but see §10 |

Flagged: **Calm A as measured in the combined table has no stop at all.** The 5%-cap rows the
current decision carries forward are the no-stop rows with an ATR budget standing in for a
stop. The disaster-stop variant is a different book.

**Nothing here is wired live.** A grep of the live runner and the production packages finds no
`roska4_calm` cluster anywhere, no forced-close or suppression machinery, and no Calm-PCLoc or
intraday-Stress-detector code path. The production arming table covers exactly two clusters,
the R4 swing basket and the NKD sleeve, and arms both at **14:00**, not 14:05. So "enforceable
live" is unproven by construction for three of the four sleeves, and the two that do exist
live are armed five minutes earlier than the artifacts assume.

---

## 2. Does the cap charge the real stop risk

| Sleeve | Cap charges | Real stop distance | Ratio |
|---|---|---|---|
| Normal-R4 | 2.5 × daily ATR × point value | 2.0 × daily ATR | Cap overstates by **25%** — conservative |
| Current NKD | 2.5 × daily ATR × point value | 2.0 × daily ATR | Same 25% overstatement |
| Stress-MNQ | abs(stop − entry) × $2 × 7 | identical | **Exact.** Confirms itself: the largest declared risk is $5,290 against a $5,000 cap, and exactly one leg is rejected |
| Calm-NKD | 2.5 × daily ATR × point value = $472 median | $11.52 median | Cap overstates by roughly **40×** |
| Calm A, combined table | 2.5 × daily ATR proxy, no stop exists | — | Not a stop risk at all |
| Calm A with 1.5 × ATR stop | abs(entry − stop) × point value | identical | **Exact** |

The 25% overstatement on the two daily-ATR sleeves is in the safe direction and is the
buffer that covers the unarmed window (§9). The Calm-NKD figure is not a rounding matter:
the cluster budget never binds on that sleeve — 758 admitted, 0 rejected on floor — because
the number it is checking against bears no relation to what the position can actually lose.

A definitional point that applies to every sleeve: declared risk excludes execution cost, so a
clean stop-out always loses slightly more than declared. That is the entire explanation for the
five Stress "breaches" and the two Calm A breaches in §4.

---

## 3. Gap-through fills

The production engine already handles this correctly: a stop hit is filled at the bar's open
whenever a real time break of more than fifteen minutes precedes that bar and the bar opened
past the stop; otherwise it fills at the stop. The Stress routine does the same thing
explicitly, filling at the open when the whole bar sits beyond the stop, and it tests the stop
before the target within a bar. The Calm A disaster-stop routine does the same for longs.

The extra correction that exists in the harness — the one that rewrites a fill booked at the
stop when the market was already through the stop at the arming instant — was **switched off**
when the trade artifacts this whole candidate stands on were generated. So the natural question
is how much it would have changed. Answer: nothing, and this is measured, not assumed.

| | floor | 2025 | 2026 |
|---|---:|---:|---:|
| chandelier stop exits examined (GAP-reason exits already fill at the open) | 81 | 13 | 6 |
| of those, exiting the session after entry | 11 | 1 | 0 |
| of those, exiting on the first bar at or after arming | **0** | 0 | 0 |
| corrections the fix would make | **0** | 0 | 0 |

A second, broader check that does not depend on the correction's own narrow conditions asks
the same thing of every booked stop exit: did that bar already open through the stop? Zero of
81, zero of 13, zero of 6. Both routes agree: on this trade set there is no unfillable stop
price, and the fill fix is a no-op. The funnel is printed above precisely so this zero can be
read as a real zero rather than as a scan that never had anything to look at.

---

## 4. Realised loss against declared risk

Declared risk is what the cluster budget was charged. Realised loss is what the trade actually
gave back.

| Window | Sleeve | n | median | p90 | max declared | worst realised loss | loss > declared | worst ratio |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| floor | Normal-R4 | 752 | $710 | $1,461 | $3,009 | $2,037 | 1 (0.1%) | 1.51 |
| floor | Current NKD | 228 | $594 | $816 | $2,103 | $1,069 | 0 | 0.85 |
| floor | Calm-NKD | 550 | $472 | $856 | $1,525 | $489 | 0 | 0.88 |
| floor | Stress-MNQ | 50 | $2,229 | $3,530 | $5,290 | $3,346 | 5 (10%) | 1.03 |
| floor | Calm A (no stop) | 349 | $580 | $1,256 | $2,062 | $538 | 0 | 0.67 |
| floor | Calm A + 1.5×ATR | 349 | $348 | $754 | $1,237 | $610 | 2 (0.6%) | 1.01 |
| 2025 | Normal-R4 | 105 | $921 | $2,359 | $3,855 | $1,985 | 0 | 0.81 |
| 2025 | Stress-MNQ | 3 | $3,465 | $3,875 | $3,978 | $163 | 0 | 0.04 |
| 2025 | Calm A + 1.5×ATR | 44 | $605 | $1,081 | $1,572 | $275 | 0 | 0.29 |
| 2026 | Normal-R4 | 81 | $1,050 | $3,051 | $3,941 | $2,457 | 0 | 0.87 |
| 2026 | Stress-MNQ | 4 | $4,014 | $5,556 | $6,107 | $1,279 | 0 | 0.30 |
| 2026 | Calm A + 1.5×ATR | 28 | $1,035 | $1,819 | $1,920 | $715 | 0 | 0.42 |

**Classification of every breach.**

The seven small ones — five Stress, two Calm A, all between 1.01 and 1.03 — are the execution
cost sitting outside the declared number. Each of them exited exactly at its stop price; the
overshoot is the round turn. Not slippage, not a bug, a definition.

The single large one is different and is a real defect. Floor, M2K, short from 2020-11-04,
declared risk $534, realised loss $807, ratio 1.51. The stop for that position sat at 1868.17
and was armed from 14:05 on 2020-11-05. Highs on the following sessions were 1835, 1840 and
1837 — all under the stop. Then on 2020-11-09 the overnight session ran from 1835 up through
1868 and on to 1943 before the cash open. The position was on its fifth day, and **the day loop
closes a max-hold position at the 09:30 open before it ever asks whether the resting stop was
touched earlier in that same session.** A live stop order would have filled near 1868. The
backtest booked 1943.50.

Scanned across every armed max-hold exit:

| Window | armed max-hold exits | where the stop was traded through earlier that session | cost of the ordering |
|---|---:|---:|---:|
| floor | 894 | 4 (0.45%) | **−$424** total, worst single case −$377 |
| 2025 | 123 | 0 | $0 |
| 2026 | 99 | 0 | $0 |

The direction is conservative — the backtest books a worse loss than an armed stop would
allow, so it is not flattering the candidate. But it is a live-versus-backtest divergence on
exactly the days that matter, and it is the only reason any Normal-R4 trade breaches its
declared risk anywhere in the sample.

---

## 5. How far price ran against each position

Measured bar by bar from entry to exit, in dollars and as a fraction of declared risk.

| Window | Sleeve | Instrument | n | median adverse | worst adverse | median favourable | adverse ÷ risk (median / p90 / max) | trades where adverse exceeded risk |
|---|---|---|---:|---:|---:|---:|---|---:|
| floor | Calm A + 1.5×ATR | MES | 164 | $48 | $406 | $59 | 0.18 / 0.57 / 0.93 | 0 |
| floor | Calm A + 1.5×ATR | MNQ | 185 | $76 | $612 | $104 | 0.17 / 0.60 / 1.01 | 2 |
| floor | Stress-MNQ | MNQ | 50 | $621 | $3,381 | $1,340 | 0.31 / 0.96 / 1.08 | 5 |
| 2025 | Calm A + 1.5×ATR | MES | 26 | $86 | $295 | $101 | 0.17 / 0.51 / 0.70 | 0 |
| 2025 | Calm A + 1.5×ATR | MNQ | 18 | $178 | $467 | $169 | 0.16 / 0.45 / 0.59 | 0 |
| 2025 | Stress-MNQ | MNQ | 3 | $294 | $1,841 | $2,796 | 0.07 / 0.46 / 0.55 | 0 |
| 2026 | Calm A + 1.5×ATR | MES | 13 | $71 | $330 | $92 | 0.10 / 0.41 / 0.50 | 0 |
| 2026 | Calm A + 1.5×ATR | MNQ | 13 | $227 | $937 | $230 | 0.13 / 0.53 / 0.55 | 0 |
| 2026 | Stress-MNQ | MNQ | 4 | $2,109 | $4,725 | $1,428 | 0.60 / 0.74 / 0.77 | 0 |

Two things worth naming. Stress runs close to its stop routinely — the ninetieth percentile of
adverse excursion is 96% of the declared risk on the floor window, so nine legs in ten of the
worst decile are within a whisker of being stopped, and the worst adverse move on a single
seven-lot leg was $3,381. That is the sleeve where a tick of real slippage matters most.

Calm A's 1.5 × ATR stop, by contrast, is barely in the trade's way: the median position never
uses more than a fifth of it, and it fires twice in 421 trades across all three windows —
never in 2025 or 2026. The 2025 and 2026 net with the stop is identical to the net without it,
to the dollar.

---

## 6. Switch behaviour and forced closes

**Stress taking over from Normal — clean.** The admission test runs against the book as it
would look *after* the same-symbol Normal position is removed, and it runs **before** anything
is closed. A Stress leg rejected on cap therefore leaves the existing Normal position alone.
That rejection path is exercised, not hypothetical: one Stress leg is rejected on floor and one
in 2026.

| Window | Normal positions closed for Stress | value of switching versus holding | Normal entries suppressed while Stress open | profit given up by that suppression |
|---|---:|---:|---:|---:|
| floor | 11 | **+$1,279** | 7 | **+$1,723** forgone |
| 2025 | 1 | +$241 | 0 | $0 |
| 2026 | 0 | $0 | 0 | $0 |

Note that the suppression is not free: on the floor window it cost more in forgone Normal
profit than the switch itself earned. The published Calm A table does not report this at all —
that branch increments no counter in the current script.

**Calm-NKD taking over from current NKD — the numbers do not mean what they say.**

The forced close is booked and it does reach the daily series; the cashflow ledger sums to the
daily series to the cent. The problem is the price it uses. The current-NKD legs are priced
from the frozen NKD file named in each artifact; the Calm-NKD legs are priced from the
continuous NKD file. Those two series differ by a **constant** back-adjustment offset —
measured bar by bar over 1.67 million overlapping bars, the floor artifact sits exactly 100.0
index points above the continuous series, and the 2025 artifact exactly 10.0 points below.
2026 uses the same file for both, offset zero.

A constant offset cancels inside a sleeve, because profit is a difference of two prices on one
scale. It does not cancel in the forced close, which subtracts a current-NKD entry on one scale
from a Calm-NKD entry on the other. Putting the close price back on the artifact's scale:

| Window | offset | forced closes | switch value published | switch value corrected | combined net published | combined net corrected | worst drawdown published → corrected |
|---|---:|---:|---:|---:|---:|---:|---|
| floor | +100.0 pts | 45 | +$340 | **+$1,790** | $72,732 | **$74,182** | $4,923 → $4,973 |
| 2025 | −10.0 pts | 7 | +$30 | **−$5** | $17,881 | **$17,846** | $3,943 → $3,948 |
| 2026 | 0 | 5 | −$3,172 | −$3,172 | $10,132 | $10,132 | $4,342 → $4,342 |

The zero-offset window not moving at all is the check that the correction is wired right.

So the published switch value is wrong by a factor of five on floor and flips sign in 2025.
Corrected, the mechanism earns $1,790 over 45 closes in-sample (about $40 a close), breaks even
in 2025, and gives up $3,172 over five closes in 2026 — an average of $634 per switch, against
a total 2026 combined net of $10,132. The whole case for the switch now rests on the in-sample
window, and the only out-of-sample window with any weight in it is sharply negative.

**Suppression of current NKD while Calm-NKD is open** works and is counted: 20 / 4 / 5 entries
suppressed across the three windows, carrying −$561 / −$1,289 / −$2,518 of profit-and-loss.
All three are negative, so suppression avoided losses in every window.

**No MNKD double-stack.** Across all three windows the book never holds two MNKD positions at
once — not two current-NKD, not two Calm-NKD, not one of each.

**One silent path.** If the price lookup at the switch instant returns nothing, the old
position is dropped from the book with no cashflow booked and no counter incremented. Measured
occurrences: zero, in all three windows. It has never fired, but it fails open.

---

## 7. Same-symbol and cluster overlap

Every instant where the book holds two positions on the same contract at once:

| Window | same-symbol pairs held | cross-cluster | opposite direction | which pairs |
|---|---:|---:|---:|---|
| floor | 10 | 10 | 5 | Calm A already open, then Normal-R4 entered: 6. Calm A already open, then Stress entered: 4 |
| 2025 | 1 | 1 | 0 | Calm A open, then Normal-R4 entered |
| 2026 | 1 | 1 | 0 | Calm A open, then Normal-R4 entered |

Stress against Normal is clean — zero pairs, in every window. Current NKD against Calm-NKD is
clean — zero pairs. Within a sleeve there are no overlaps either, so no engine is double-
stacking itself.

The two failures are both on the Calm A side and both come from the same root: the skip rule is
written in one direction only.

**Normal entering on top of an open Calm A.** Calm A is suppressed when a same-symbol Normal or
Stress position is already open. Nothing stops the reverse. Calm A runs 10:00 to 15:55; Normal
enters between 14:00 and 15:55. The window overlaps by nearly two hours every day, and it
happened 6 times on floor, once in each of the other windows.

**Stress entering on top of an open Calm A — and the Calm position being paid out twice.**
Under the chosen skip-same-symbol policy, the code that decides which positions survive the
Stress entry keeps a same-symbol Calm position, but the code that decides which positions get
closed and cashed out includes it. The result is that the Calm position is settled at the
Stress entry price **and left running to its own 15:55 exit, where it settles again.** Four
occurrences on floor; the duplicated cashflows total −$635. So for those four afternoons the
book was actually holding a Calm long and a seven-lot Stress short on the same contract at the
same time — the exact same-symbol netting exposure this design says it exists to avoid — and
the published floor net of $72,732 is not a number in which every position settles once.

**Cross-cluster exposure is uncapped by design, and that design does not carry over.** The
cluster guard checks each cluster against its own budget and nothing else. The written
justification for that independence is that the clusters occupy different correlation groups or
different session windows — which holds for the Tokyo NKD sleeve, and holds for Stress because
the switch keeps it from coexisting with Normal. It does **not** hold for the new Calm cluster,
which trades MES and MNQ, in the New York session, on the same days as Normal-R4. Two 5% gross
budgets on the same four contracts in the same session add to 10% with nothing checking the sum.

---

## 8. Fill and timing

| Window | Sleeve | n | entry price outside its bar | exit price outside its bar | signal after entry | exit at or before entry | bars missing |
|---|---|---:|---:|---:|---:|---:|---:|
| floor | Normal-R4 | 752 | 0 | 0 | 0 | 0 | 0 |
| floor | Current NKD | 228 | 0 | 0 | 0 | 0 | 0 |
| floor | Stress-MNQ | 50 | 0 | 0 | 0 | 0 | 0 |
| floor | Calm A | 349 | 0 | 0 | 0 | 0 | 0 |
| floor | Calm-NKD | 550 | **547** | **527** | 0 | 0 | 1 |
| 2025 | all except Calm-NKD | 105/31/3/44 | 0 | 0 | 0 | 0 | 0 |
| 2025 | Calm-NKD | 90 | **41** | **58** | 0 | 0 | 2 |
| 2026 | all except Calm-NKD | 81/26/4/28 | 0 | 0 | 0 | 0 | 2 (see below) |
| 2026 | Calm-NKD | 44 | 0 | **20** | 0 | 0 | 0 |

The Calm-NKD rows are the price-series offset of §6 showing up again, from a completely
different direction — and they confirm it. The window where the two files are identical (2026)
is the only one where the entry check passes. That is as clean a corroboration as this audit
produced: two unrelated measurements, one comparing files bar by bar and one comparing trade
prices to bars, agree on which windows are contaminated.

Because of that offset, **the Calm-NKD legs cannot be fill-audited against the frame the rest
of the book uses.** That check is not "passed" and not "failed" — it has not been run on a
common basis.

Two Calm A legs in the 2026 sanity window fall on 2026-08-19, a session the promotion artifact
excludes because its end date clips at the start of that day. Small, but the two books do not
cover exactly the same final session.

**Timestamp conventions, stated because they differ between sleeves.** Stress and Calm A carry
one-minute timestamps and fill inside the stamped bar. The three swing sleeves stamp the entry
with the **start** of the five-minute resume bar while filling at that bar's **close**, five
minutes later. The combined replay orders events by that stamp, so a swing entry is placed in
the event sequence five minutes earlier than it can physically occur. It has not changed any
result measured here — Calm A enters at 10:00 and Stress after 10:35, both well clear of the
14:00–15:55 swing window — but it is a latent ordering error if any future sleeve trades in
that window.

---

## 9. Causality

All clean. Each was traced to the function that produces the value, not to a comment.

**Normal-R4.** The short filter reads the previous day's SPY close against its 50-day average.
The R4 admission filter reads the prior session's range and the volume of the resume bar, which
is complete at the moment of the fill. Nothing looks forward.

**Stress-MNQ.** Every input — each instrument's position against its open and its volume-
weighted average price, the gap against the prior session's cash close — comes from five-minute
bars that complete at 10:35. The entry scan starts at 10:35 and runs to 12:30. Zero legs in any
window have their signal timestamped after their entry.

**Calm-NKD.** The regime gate takes the SPY label of the previous calendar day and exposes the
Tokyo session only on days where that label was Calm. The Tokyo session that gets labelled for
a given date opens around 19:00 New York time on the day before, which is after that day's SPY
close — so the label is known roughly two hours before the first bar it can act on.

**Calm A.** The prior-session shape features come from full cash sessions that reached 15:55,
shifted one day. The gap uses today's 09:30 open. The regime gate takes the strictly previous
labelled day. Entry is at 10:00, thirty minutes after the last input becomes known.

**One exposure worth naming even though it is not lookahead.** Normal-R4 and current NKD hold
for roughly twenty-three hours with no stop in the market, between the fill and the next
session's arming. Measured across 980 trades on the floor window:

| Instrument | n | median hours unprotected | median adverse move | worst adverse move | worst as a fraction of the stop distance | trades that ran past the stop while unprotected |
|---|---:|---:|---:|---:|---:|---:|
| MES | 188 | 23.2 | $85 | $631 | 1.11 | 2 |
| MNQ | 186 | 23.1 | $151 | $1,156 | 0.86 | 0 |
| MYM | 200 | 23.2 | $79 | $438 | 0.98 | 0 |
| M2K | 178 | 23.2 | $66 | $349 | 0.93 | 0 |
| MNKD | 228 | 23.6 | $98 | $930 | 0.84 | 0 |

Not one of the 980 trades moved further against the position than the declared cluster risk
while unprotected, and only two ever passed the stop level itself. The 25% overstatement in the
declared number covered the unarmed window in every historical case. That is an empirical
result on this sample, not a structural guarantee.

---

## 10. The Calm-NKD sleeve on its own terms

This is the finding that goes beyond bookkeeping. The Calm-NKD challenger is not the current
NKD sleeve with a different gate — it is a different trade.

| | Current NKD | Calm-NKD challenger |
|---|---:|---:|
| Stop mechanism | fixed, 2.0 × daily ATR, armed next session | trailing chandelier on 5-minute ATR, live from the session boundary |
| Median stop distance, floor | 916 index points ($458) | **23 index points ($11.52) — 4.6 ticks** |
| Share of trades stopped out, floor | 11% | **87%** |
| Win rate, floor | 50.4% | **12.9%** |
| Median loss | −$171 | **−$23** |
| Trades, floor | 228 | 550 |
| Net, floor | $3,898 | $7,156 |
| Declared cluster risk, median | $594 | $472 |

The stop is 4.6 ticks wide while the assumed round-turn cost is 4 ticks. What one extra tick of
adverse fill on the stop exits does to each sleeve:

| Window | Calm-NKD as measured | +1 tick | +2 ticks | +3 ticks | Current NKD +3 ticks |
|---|---:|---:|---:|---:|---:|
| floor | $7,156 | $5,958 (−17%) | $4,761 (−33%) | $3,563 (−50%) | $3,711 (−1.6% from $3,898) |
| 2025 | $2,477 | $2,280 | $2,082 | $1,885 | $2,181 (−1.0%) |
| 2026 | $1,543 | $1,453 | $1,363 | $1,273 | $4,277 (−0.3%) |

Half the floor edge is inside three ticks of stop-fill slippage, on a sleeve that gets stopped
out 87% of the time. The median stop widens across the windows — 4.6 ticks, then 8.8, then 17.7
— as the Nikkei level rose, so the newest data is the least fragile, but the in-sample result
that carries the case is the most fragile part of it.

And the cluster cap does not see any of this: it charges $472 against a position that can lose
$12, which is why 758 legs are admitted and none rejected.

---

## 11. Calm A's disaster stop makes the cap honest and the exposure larger

Worth stating plainly because it is easy to read the wrong way. Adding the 1.5 × ATR stop lets
the cap charge a true stop risk instead of a proxy. That true risk is **smaller** than the
proxy — median $348 against $580 on floor — so the same 5% budget admits more trades:

| Window | no stop, admitted / rejected | with 1.5×ATR stop, admitted / rejected |
|---|---:|---:|
| floor | 335 / 7 | 342 / 0 |
| 2025 | 38 / 4 | 42 / 0 |
| 2026 | 15 / 12 | 26 / 1 |

The 2026 window is the sharp one: the honest cap admits 26 legs where the proxy cap admitted
15. The stop itself fires twice in 421 trades and never once outside the floor window. So the
change is almost entirely a change to the admission arithmetic, not to the protection. That may
still be the right call — it replaces a made-up number with a real one — but it should be
adopted knowing it loosens the sleeve rather than tightens it.

---

## 12. Verdict

### Is the combined candidate stop/risk-clean enough for a production feasibility audit?

**No — not as the stack is currently specified.** Three of the four sleeves are clean or
fixable-clean. The blockers are concentrated in the two switch mechanisms and in the Calm-NKD
sleeve's risk definition.

What is already clean, and would survive as-is:

- Normal-R4's stop is real, fixed, verified to the basis point, and its cap is conservative
  by a measured 25%.
- Stress-MNQ's cap charges the exact stop risk; its switch checks admission before it closes
  anything, and a rejected Stress leaves the existing book untouched.
- No unfillable stop fills anywhere; the gap-through fix is a measured no-op on this trade set.
- Causality is clean in all four sleeves.
- No double-stacking within any sleeve; no MNKD double-stack; no Stress-on-Normal overlap.
- Fill and timing are clean for Normal-R4, current NKD, Stress and Calm A.

### Blockers

1. **The Stress entry settles a same-symbol Calm A position twice and leaves it open.** Four
   occurrences on floor, duplicated cashflows −$635. The consequence is not only the money: for
   those afternoons the book genuinely held a Calm long and a seven-lot Stress short on the same
   contract, which is the netting exposure the switch design exists to prevent. Decide whether
   Stress should override Calm at all under the chosen policy, then make the close list and the
   survivor list agree.

2. **Normal-R4 can open on a contract where Calm A is already running.** Six times on floor,
   once in each other window. The skip rule needs to be symmetric, or the two sleeves need a
   shared same-symbol lock.

3. **The Calm-NKD switch is measured across two different NKD price series.** The forced close
   subtracts prices on scales that differ by a constant 100 points on floor and 10 points in
   2025. Corrected, the switch's own value goes from +$340 to +$1,790 on floor and from +$30 to
   −$5 in 2025, and the combined net moves from $72,732 to $74,182 and from $17,881 to $17,846.
   Until both sleeves are regenerated from one file, the published switch numbers should not be
   used for a decision. The one window that already uses a common file reports the mechanism
   giving up $3,172 over five closes — so after correction the switch's case rests entirely
   in-sample and its only clean out-of-sample reading is sharply negative.

4. **Calm-NKD's declared risk is roughly forty times its real stop risk**, so its cluster cap
   cannot bind, and its stop is 4.6 ticks wide against a 4-tick assumed cost. Either give it the
   same fixed daily-ATR stop the rest of the book uses and re-measure, or accept it as a
   deliberately different mechanism and give it a risk definition and a cap that match what it
   can actually lose.

5. **The Calm cluster shares instruments and session with the Normal cluster while the guard
   caps each independently.** Two 5% gross budgets on MES and MNQ in the same afternoon add with
   nothing checking the sum. This needs an explicit decision — either a combined roska4 ceiling
   or a written argument for why independence holds here, of the kind the NKD cluster already
   has.

### Defects to fix, not blocking

6. Max-hold exit pre-empts the armed stop. Four cases in 894 on floor, $424 total, all in the
   conservative direction. Ask the stop question before the max-hold question on the exit day.
7. The forced-close price lookup drops a position silently when no bar is found. Zero
   occurrences so far; it should raise or count, not vanish.
8. The published Calm A replay does not count Normal entries suppressed by an open Stress
   position. On floor those were 7 entries worth $1,723 of forgone profit.
9. Production arms stops at 14:00; the artifacts assume 14:05.
10. The three swing sleeves stamp entries with the start of the five-minute resume bar while
    filling at its close. Harmless today, latent if a future sleeve trades that window.
11. Two Calm A legs in the 2026 window fall on a session the rest of the book excludes.

### If the blockers are cleared, what remains before a production patch

- Everything in the existing "Open Gates" list that this audit does not touch: regenerate the
  full replay from the production signal path rather than captured artifacts, and run a live
  paper window with real broker events.
- Wire-up work is untouched ground: no Calm cluster, no switch machinery and no Calm/Stress
  code path exists in the live runner today, so none of the switch semantics has ever been
  exercised against a broker.
- Stress's out-of-sample evidence is three legs in 2025 and four in 2026, and its adverse
  excursion routinely reaches 96% of its stop. Concentration and slippage sensitivity on that
  sleeve are open questions this audit did not close.
- The MNKD contract in use expires 2026-09-04. Both NKD sleeves depend on it.

---

## Artifacts

- `scratch/combined_stop_risk_audit_20260822.py` / `_report.md` / `.json` — main audit and
  instrumented replay
- `scratch/combined_unarmed_window_probe_20260822.py` / `.json` — exposure between fill and
  arming
- `scratch/combined_maxhold_stop_order_probe_20260822.py` / `.json` — max-hold versus armed
  stop ordering, and the NKD price-series comparison
- `scratch/combined_nkd_offset_correction_20260822.py` / `.json` — the switch result with the
  price scales reconciled
