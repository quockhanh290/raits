# Calm-NKD Tight-Stop Tail-Capture — Standalone Strategy Audit — 2026-08-22

Scratch-only. No production file changed.

The earlier verdict rejected Calm-NKD only as a same-risk-model replacement for the current NKD
sleeve. That did not settle whether the tight-stop version is a strategy in its own right, on its
own stop. This audits it as one.

## Verdict: **REJECT**

Not for slippage, not for concentration, not for the cap. **For fill impossibility.** The entire
measured edge is the backtest closing positions at a stop price the market had already passed
hours earlier. Once the fill is made possible, the strategy loses money in every window and at
every parameter value.

Three independent measurements agree, and two of them agree to the dollar.

---

## 1. Reconstructed strategy definition

Rebuilt from the engine, not from the description.

| | |
|---|---|
| Instrument | MNKD, point value $0.50, tick 5.0 index points ($2.50), commission $1.40 round turn |
| Data | `global_index/data/NKD_continuous_1m_8y.parquet`, converted to Asia/Tokyo |
| Engine | `futures._validated_core.backtest_swing_tf`, raw and unpatched |
| Gate | D-1 Calm, causal — the previous labelled day's SPY regime, presented to the signal as "Normal" |
| Entry | close of the 5-minute resume bar inside the 14:00–15:55 window **of the frame's own clock**, i.e. Tokyo afternoon |
| Initial stop | chandelier on the resume bar alone: bar extreme ∓ 2.5 × ATR14 of the **5-minute** bars |
| Trail | ratchet is on, but it trails on **daily** ATR and is combined against the initial stop with max()/min(), so the tight initial stop normally binds throughout |
| Stop arming | **none** — the stop is first checked at the first bar of the next calendar day in the frame's timezone |
| Gap fill | fill at the bar open only when a real time break of more than fifteen minutes precedes the triggering bar and that bar opened beyond the stop; otherwise fill at the stop |
| Max hold | 5 days; for a non-ET frame the exit is the **first bar of the day** |
| Cost | 2 ticks per side |

The two lines that decide this audit are **stop arming** and **gap fill**, and they interact.

## 2. Anchor — passed, exactly

Every one of the six original variants was rebuilt and compared trade-for-trade against the list on
disk: count, every entry, every exit, every P&L, every exit reason.

| Window | variants checked | exact |
|---|---:|---|
| IS 2018-2024 | 6 | **6/6** |
| OOS 2025 | 6 | **6/6** |
| SANITY 2026 | 6 | **6/6** |

The headline candidate reproduces to the dollar: `ema5_mult2.5` on floor = 550 trades, **+$7,156**,
PF 1.55, win rate 12.9%. So what follows is measured on exactly the book that produced the old
claim.

## 3. Standalone metrics, as shipped

| Window | ema | n | net | ret | PF | Sharpe | Calmar | MaxDD | win rate | avg win | avg loss | stop rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| floor | 5 | 550 | +$7,156 | 14.3% | 1.55 | 1.60 | 0.78 | $1,318 | 12.9% | $283 | −$27 | 87.1% |
| floor | 10 | 560 | +$3,542 | 7.1% | 1.25 | 0.88 | 0.17 | $2,950 | 12.1% | $257 | −$28 | 88.0% |
| floor | 15 | 548 | +$4,410 | 8.8% | 1.32 | 1.09 | 0.33 | $1,923 | 13.0% | $254 | −$29 | 87.4% |
| floor | 20 | 556 | +$5,470 | 10.9% | 1.40 | 1.28 | 0.48 | $1,635 | 12.9% | $268 | −$28 | 87.4% |
| 2025 | 5 | 90 | +$2,477 | 5.0% | 1.92 | 2.33 | 3.43 | $736 | 12.2% | $471 | −$34 | 87.8% |
| 2025 | 10 | 86 | +$1,249 | 2.5% | 1.40 | 1.23 | 1.88 | $680 | 12.8% | $399 | −$42 | 86.0% |
| 2025 | 15 | 85 | +$821 | 1.6% | 1.25 | 0.84 | 0.86 | $978 | 12.9% | $370 | −$44 | 85.9% |
| 2025 | 20 | 86 | +$499 | 1.0% | 1.14 | 0.50 | 0.51 | $998 | 11.6% | $395 | −$45 | 87.2% |
| 2026 sanity | 5 | 44 | +$1,543 | 3.1% | 1.51 | — | — | — | 13.6% | — | — | 81.8% |
| 2026 sanity | 10 | 40 | +$6,001 | 12.0% | 3.99 | — | — | — | 22.5% | — | — | 75.0% |

Note already that ema5 is the top cell on floor and its nearest neighbour, ema10, returns 49% of it.
The project's own plateau rule — neighbouring cells within ±30% — is not met. And the ranking is not
stable: floor orders 5 > 20 > 15 > 10, 2025 orders 5 > 10 > 15 > 20, 2026 orders 10 > 15 > 20 > 5.
Only "ema5 is best" is stable, and only on the two windows it was chosen from.

## 4. Stop / risk distribution

| Window | ema | median stop | p90 | max | in ticks (median) | declared ATR-proxy risk | declared ÷ true |
|---|---:|---:|---:|---:|---:|---:|---:|
| floor | 5 | 22.6 pts / **$11.30** | $28.14 | $122.32 | **4.5** | $472 | **42×** |
| floor | 10 | 25.7 pts / $12.85 | $31.08 | $122.32 | 5.1 | $476 | 37× |
| 2025 | 5 | 44.9 pts / $22.45 | $43.02 | $189.02 | 9.0 | $853 | 38× |
| 2026 | 5 | 87.2 pts / $43.62 | — | — | 17.4 | — | — |

The stop widens as the Nikkei level rises — 4.5 ticks, then 9.0, then 17.4 — so the in-sample window
that carries the whole case is also the most fragile part of it.

## 5. Fill realism — this is where it dies

The question that matters for a 4.5-tick stop: was any exit booked at the stop price on a bar that
had **already opened beyond it**? That fill is not conservative or optimistic — it is impossible.

| Window | ema | chandelier exits | **impossible fills** | favourable dollars | exits priced outside their own bar |
|---|---:|---:|---:|---:|---:|
| floor | 5 | 471 | **290 (62%)** | **$13,297** | 275 |
| floor | 10 | — | 314 | $15,279 | 299 |
| floor | 15 | — | 303 | $14,243 | 292 |
| floor | 20 | — | 316 | $14,330 | 302 |
| 2025 | 5 | — | 57 | $4,022 | 54 |

**$13,297 of impossible benefit against $7,156 of net.**

### The mechanism

Of the 290 impossible fills on floor, **248 occur at 00:00–00:01 JST**, and for **228** of them the
previous bar is exactly **one minute** earlier.

The engine checks a carried position's stop once per calendar day, at the start of that day's bar
group. For a Tokyo-timezone frame the day boundary is **midnight JST — the middle of a continuously
trading session**. A position entered at 14:00–15:55 JST is not stop-checked again for eight to ten
hours. By the time the engine looks, price has often walked straight past a 22-point stop. Because
no time break precedes that bar — the market never stopped trading — the gap-fill rule does not
engage, and the engine books the exit **at the stop price**, which nobody could have got.

Worked examples from the floor book:

| exit bar | dir | bar open | bar high | bar low | booked at stop | free gift | gap before bar |
|---|---|---:|---:|---:|---:|---:|---:|
| 2018-03-23 00:00 JST | LONG | 20,150 | 20,165 | 20,150 | **20,463.2** | 313 pts | 1 min |
| 2018-03-10 00:00 JST | SHORT | 20,710 | 20,720 | 20,705 | **20,518.0** | 192 pts | 1 min |
| 2018-01-25 00:00 JST | LONG | 22,805 | 22,805 | 22,800 | **22,899.6** | 95 pts | 1 min |

The booked exit sits hundreds of points outside the bar's entire range.

### Corroboration one: rerun with the fill made possible

Fill at the bar open whenever the bar opened beyond the stop:

| Window | ema | as shipped | **conservative fill** | PF | delta |
|---|---:|---:|---:|---:|---:|
| floor | 5 | +$7,156 | **−$6,141** | 0.77 | **−$13,297** |
| floor | 10 | +$3,542 | **−$11,737** | 0.60 | −$15,279 |
| floor | 15 | +$4,410 | **−$9,833** | 0.65 | −$14,243 |
| floor | 20 | +$5,470 | **−$8,860** | 0.68 | −$14,330 |
| 2025 | 5 | +$2,477 | **−$1,545** | 0.77 | −$4,022 |
| 2025 | 10 | +$1,249 | **−$2,381** | 0.65 | −$3,631 |
| 2025 | 15 | +$821 | **−$2,668** | 0.60 | −$3,489 |
| 2025 | 20 | +$499 | **−$3,429** | 0.54 | −$3,928 |
| 2026 sanity | 5 | +$1,543 | −$4,102 | 0.53 | −$5,645 |
| 2026 sanity | 10 | +$6,001 | +$2,067 | 1.35 | −$3,934 |

Every delta equals the fill audit's impossible-dollar figure **exactly**. Gap exits go from 8 to 298
on floor ema5 — matching the 290 impossible fills plus the 8 that were already gap exits. Two
measurements built on different code paths, agreeing to the dollar.

**Negative in floor and in 2025, at every ema.** PF 0.53–0.77.

### Corroboration two: how far price ran against the position

| Window | ema | median adverse move | p90 | max | median ÷ true stop risk | trades whose adverse move exceeded their own stop |
|---|---:|---:|---:|---:|---:|---|
| floor | 5 | $42.5 | $132.8 | $1,082.5 | **3.62×** | **519 of 550 (94%)** |
| 2025 | 5 | $90.0 | $198.0 | $485.0 | **4.42×** | **85 of 90 (94%)** |

Ninety-four per cent of trades ran past their own stop before the backtest closed them at it. A stop
that is actually in the market does not let that happen.

## 6. Slippage stress — reported as requested, but moot

Computed on the as-shipped book, which does not survive section 5. Included because it was asked for
and because it shows the fragility from yet another angle.

| Window | +0 | +1 tick | +2 | +3 | +5 |
|---|---:|---:|---:|---:|---:|
| floor net | $7,156 | $5,958 (−17%) | $4,761 (−33%) | $3,563 (−50%) | $1,168 (−84%) |
| floor PF | 1.55 | 1.42 | 1.31 | 1.22 | 1.06 |
| floor Calmar | 0.78 | 0.57 | 0.40 | 0.27 | 0.07 |
| 2025 net | $2,477 | $2,280 | $2,082 | $1,885 | $1,490 |
| 2025 PF | 1.92 | 1.79 | 1.67 | 1.57 | 1.40 |

All exits, +1 / +2 ticks: floor $5,781 / $4,406; 2025 $2,252 / $2,027.

Worsening the stop fill does not change *which* trades stop out, so this adjustment is exact rather
than approximate. Floor Calmar falls below 0.30 at +3 ticks — on a book that is already fictitious.

## 7. Concentration

| Window | ema | top 1 | top 3 | top 5 | best year | net excluding best year | positive years |
|---|---:|---:|---:|---:|---|---:|---|
| floor | 5 | 15.4% | 36.0% | **53.7%** | **2021 = 48.9%** | $3,653 | 5 / 7 |
| floor | 10 | 19.6% | 56.2% | 89.7% | 2021 = 71.8% | $999 | 5 / 7 |
| floor | 15 | 15.7% | 45.1% | 72.0% | 2021 = 62.4% | $1,660 | 5 / 7 |
| floor | 20 | 14.1% | 38.7% | 62.1% | 2021 = 58.3% | $2,282 | 5 / 7 |
| 2025 | 5 | **46.5%** | **89.5%** | **131.3%** | — | — | 1 / 1 |

Five winning trades carry more than half the in-sample net, and one year carries nearly half. In
2025 the top five winners are worth more than the entire net — every other trade nets negative.
This would have been a flag on its own; it is not the reason for rejection.

## 8. Cap design

The NKD cluster budget is 6% of $50,000 = $3,000. Against a median true risk of $11.30:

| minimum charge per trade | median charged | concurrent positions needed before the budget refuses anything |
|---:|---:|---:|
| none (true risk) | $11.30 | **266** |
| $25 | $25.00 | 120 |
| $50 | $50.00 | 60 |
| $100 | $100.00 | 30 |
| $200 | $200.00 | 15 |
| $300 | $300.00 | 10 |

The engine holds **at most one position at a time**. So the cap cannot bind at any minimum charge up
to $300; making it bind would require charging roughly $3,000 per trade, 265× the true risk — a
number with no derivation behind it. This meets the pre-stated rejection condition that the cap only
binds through an arbitrary minimum charge.

## 9. Portfolio integration

**Not run.** The specification says to test it only after the standalone passes. It does not pass, and
adding a sleeve whose measured book depends on impossible fills would put that dependency into the
portfolio number rather than test it.

## 10. Verdict against the pre-stated rejection rules

| Rule | Result |
|---|---|
| edge dies under +2 stop-exit ticks, or materially degrades under +1 | **degrades 17% at +1, 33% at +2** — fails |
| PF < 1.20 on floor or 2025 | as shipped 1.55 / 1.92 — passes; **with possible fills 0.77 / 0.77 — fails** |
| Calmar benefit only from one year or top 1–3 trades | 2021 = 49% of net, top 5 = 54% — borderline fail |
| cap only binds through an arbitrary minimum charge | **fails** — would need ~$3,000, 265× true risk |
| fill audit finds impossible stop fills | **fails outright** — 290 of 471, $13,297, more than the whole net |
| portfolio improvement mostly from relaxing risk rather than edge | not reached |
| same-symbol broker/netting cannot be implemented cleanly | not reached |
| 2025 survives only through post-hoc tuning | 2025 is negative once fills are possible |

**REJECT.** The hypothesis was worth testing and it was tested on its own terms, with its own stop,
with no requirement to match the current sleeve's risk model. It fails on measurement, not on
principle: the tail capture is not a market effect, it is the day-boundary stop check.

## What would have to change before this is measurable again

The obstacle is structural, not a parameter. This engine checks a carried stop once per calendar day
in the frame's own timezone, and for MNKD that boundary lands mid-session. Any stop tighter than the
typical eight-to-ten-hour move between the entry session and midnight JST **cannot be evaluated by
this code path at all** — it will always be booked at a price the market had already left.

A same-session stop path does exist (`model_sameday_stop.run_loop` with `same_day_stop=True`), which
makes the stop live from the fill. If tight-stop tail capture on NKD is worth another look, that is
the only harness that can measure it honestly. I am not predicting it would pass: the one row above
that survives possible fills is 2026 ema10, 40 trades, and 2026 is a sanity window.

## Artifacts

- `scratch/calm_nkd_tight_stop_audit_20260822.py` — anchor gate, stop/risk, fill, concentration,
  slippage, cap
- `scratch/calm_nkd_tight_stop_audit_20260822.json`
- this report
