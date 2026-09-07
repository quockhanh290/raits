# Stage 5ZZZ-J — a causal pre-14:00 SPY regime proxy for Swing

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

## Decision

# `KEEP_RESEARCH_ONLY`

The proxy avenue is closed, and it closed **in-sample** — before the missing out-of-sample data ever became the binding constraint. Two independent failures, either one sufficient:

1. **It is worse than D-1 at its own job.** Recovering the same-day label: D-1 **91.6%**, proxy **82.8%**.
2. **It loses money on the window it was built on.** Swing's contribution under the proxy is **−$2,433** on the floor, and the whole route with it (**$45,603**) is worse than deleting the sleeve (**$49,414**).

And separately, promotion was never reachable: **SPY intraday data ends 2024-12-30.** There is not one bar in 2025 or 2026.

---

## 1. Does the data exist? Floor yes, OOS no

Every SPY intraday file on disk, unioned:

```text
504,239 bars over 1,999 sessions      2017-01-03 .. 2024-12-30
```

| Window | sessions | with a ~14:00 bar | expected | verdict |
|---|---:|---:|---:|---|
| floor 2018-2024 | 1,748 | **1,732** | ~1,763 | **OK** (98%) |
| 2025 OOS | **0** | **0** | ~251 | **INSUFFICIENT** |
| 2026 OOS | **0** | **0** | ~158 | **INSUFFICIENT** |

The promotion bar in the brief requires the proxy to *beat D-1 OOS* and be *competitive with no-Swing OOS*. Neither is measurable. Promotion was arithmetically unreachable from the first measurement, and everything below is about whether the idea is worth revisiting when data exists.

**ES intraday does cover all three windows** (`ES_continuous_1m_8y.parquet`, 3,375,148 bars to 2026-08-28). That is the obvious substitute instrument, and §6 says why I did not simply swap it in.

---

## 2. Is the proxy causal? Yes, by construction

Features, all closed by 14:00 ET on the session being labelled:

```text
gap                 open(09:30) / prev session close - 1
ret_to_1400         close(14:00) / prev session close - 1
ret_open_to_1400    close(14:00) / open(09:30) - 1
range_to_1400       (high - low through 14:00) / prev session close
rvol_1400           realised vol of 5-minute returns, 09:30-14:00
rvol_5d_prior       the above, 5-session mean, SHIFTED one session
absret_5d_prior     |ret_to_1400|, 5-session mean, SHIFTED one session
```

The 16:00 close of the session being predicted is never read. The previous session's close is, and that is known before the session opens. The model is refit every 126 sessions on everything strictly before, so no session is predicted by a model that saw it — the first ~18 months are warm-up and get no prediction at all, which is carried into the backtest rather than papered over.

---

## 3. Proxy versus the daily label

Scored on 1,370 sessions, 2019-07-05 → 2024-12-30.

| predictor of the **same-day** label | accuracy |
|---|---:|
| always the majority class (Normal) | 48.3% |
| **carry yesterday forward (D-1)** — the bar to beat | **91.6%** |
| **causal pre-14:00 proxy** | **82.8%** |
| difference | **−8.8 points** |

Confusion, proxy (rows) against the same-day label (columns):

```text
          Calm   Normal   Stress
Calm       520      120        0
Normal      59      560       36
Stress       0       21       54
```

### Where the 8.8 points go

```text
D-1 is WRONG on   115 sessions  (8.4%)   proxy fixes  48.7%  ->  +56 sessions
D-1 is RIGHT on 1,255 sessions           proxy keeps  85.9%  -> -177 sessions
                                                       net    -121 sessions
```

1,255 − 121 = 1,134, and 1,134 / 1,370 = 82.8% — the arithmetic closes.

**That is the mechanism, and it is not a tuning problem.** The same-day label is *defined* by the 16:00 close, so a 14:00 feature set is missing the final two hours by construction. Meanwhile the label is enormously persistent — yesterday's answer is right nine times in ten. A proxy has to beat 91.6% to add anything, and intraday movement through 14:00 breaks three correct calls for every one it fixes.

---

## 4. In the full stack

Account $50,000 · 1 micro · 2 ticks/side · family cap 5.0%/4.4% · production fill law · HMM fit end per window. Baseline reproduced 30/30 in Stage 5ZZZ-H and unchanged since.

### Full stack, Calm-NKD ON

| Window | Route | Net | PF | Sharpe | Calmar | MaxDD | trades | Swing $ |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **floor** *(in-sample)* | same-day *(not live-tradable)* | $74,410 | 1.67 | 2.12 | 2.14 | $4,973 | 1690 | +$25,677 |
| | D-1 daily | $66,796 | 1.59 | 1.91 | 1.92 | $4,973 | 1696 | +$18,429 |
| | D-1 daily, retuned | $64,374 | 1.55 | 1.83 | 1.78 | $5,186 | 1710 | +$16,883 |
| | **causal pre-14:00 proxy** | **$45,603** | 1.42 | 1.45 | 1.38 | $4,736 | 1523 | **−$2,433** |
| | no Swing | $49,414 | **1.82** | **2.19** | 1.84 | **$3,842** | 1156 | $0 |
| **2025** *(OOS)* | same-day | $16,997 | 2.26 | 2.76 | 4.45 | $3,901 | 214 | +$4,690 |
| | D-1 daily | $16,181 | 2.05 | 2.50 | 3.36 | $4,915 | 215 | +$3,906 |
| | D-1 daily, retuned | $10,040 | 1.66 | 2.16 | 2.52 | $4,065 | 221 | −$2,190 |
| | **causal proxy** | — **no SPY intraday data** — | | | | | | |
| | no Swing | $12,377 | **3.01** | **3.90** | **8.05** | **$1,568** | 163 | $0 |
| **2026** *(OOS)* | same-day | $9,288 | 1.62 | 2.47 | 3.41 | $4,342 | 129 | +$719 |
| | D-1 daily | $8,105 | 1.52 | 2.14 | 3.76 | $3,435 | 127 | −$464 |
| | D-1 daily, retuned | $6,946 | 1.43 | 1.87 | 3.04 | $3,644 | 132 | −$1,623 |
| | **causal proxy** | — **no SPY intraday data** — | | | | | | |
| | no Swing | **$8,731** | **2.02** | **3.46** | **8.92** | **$1,561** | 87 | $0 |

Swing accepted/rejected under the proxy on the floor: **386 / 182**, against 545/190 for same-day and 564/197 for D-1.

### Risk-clean, no Calm-NKD — floor

| same-day | D-1 | D-1 retuned | **proxy** | no Swing |
|---:|---:|---:|---:|---:|
| $64,903 | $57,289 | $54,867 | **$36,096** | $39,907 |

The proxy is last in both policies, and **below the no-Swing route in both**.

---

## 5. What that means

The proxy does not merely underperform the label it replaces — **it makes the sleeve actively harmful in-sample**. Swing contributes −$2,433 under it, having taken 367 more positions than the no-Swing route and finished behind it.

The warm-up is worth addressing before anyone offers it as the explanation. The proxy has no labels for 2018-01 → 2019-07, so the sleeve refused there and lost eighteen months of trades it would otherwise have taken. But the no-Swing route refuses on *every* session of all seven years and still finishes $3,811 ahead. Missing trades is not what sank it; the trades it did take are.

---

## 6. Why I did not just switch to ES

ES intraday covers every window and would remove the data obstacle. I did not swap it in, because the floor result says the obstacle is not the instrument.

The failure is structural: the target label is a function of the 16:00 close, and it persists at 91.6% day over day. Any pre-14:00 feature set — SPY, ES, or both — is predicting the same quantity from the same two-hours-short vantage. ES tracks the same underlying as SPY; there is no reason to expect its 14:00 snapshot to recover the 16:00-defined label materially better, and a stage that spent an hour confirming that would be spending it to reach a conclusion the mechanism already implies.

If the operator wants that confirmed rather than argued, it is a defined and affordable next step — and it should be run as a **label-recovery test first**, exactly as here, because that test costs minutes and settles the question before any backtest is built.

---

## 7. Answers

| question | answer |
|---|---|
| Historical SPY intraday exists | **Floor yes** (1,732 of ~1,763 sessions have a 14:00 bar). **2025 and 2026: zero bars.** Data ends 2024-12-30 |
| Proxy is causal | **Yes** — every feature closes by 14:00; walk-forward refits; the predicted session's close is never read |
| Proxy vs daily-label agreement | **82.8%** against D-1's **91.6%**. Fixes 56 of D-1's errors, breaks 177 of its correct calls |
| Full stack, floor | same-day $74,410 · D-1 $66,796 · retuned $64,374 · **proxy $45,603** · no-Swing $49,414 |
| Risk-clean, floor | $64,903 · $57,289 · $54,867 · **$36,096** · $39,907 |
| 2025 / 2026 | **not measurable** — no SPY intraday data |
| Swing remains research-only | **Yes.** Enabled in shadow, not paper-orderable |
| `orders_possible` | **False** — `PAPER_SHADOW_EVIDENCE` |

---

## 8. Caveats, and what I am not claiming

- **One proxy design.** A multinomial logistic regression over seven features. A different model or feature set could score differently — but it would still be predicting a 16:00-defined label from 14:00 information against a 91.6% persistence baseline, and that is the part that does not move.
- **The floor is in-sample**, and it is the *only* window measurable. The P&L comparison in §4 for the proxy is in-sample only and must never be quoted as an out-of-sample result.
- **The proxy arm carries an 18-month coverage hole** by construction. Argued above why that does not rescue it, but it does mean the floor P&L is not a like-for-like trade count.
- **No bootstrap.** No difference here has been tested against noise. The label-recovery gap is large and mechanically explained; the P&L gap is not separately significance-tested.

## Safety

```text
orders_possible False · blocking ['PAPER_SHADOW_EVIDENCE'] · scheduler pid 3000, not restarted
no broker call · orders dir ABSENT · TRACK1_ORDERS_APPROVED unset · confirmation intact
no live route code changed · runtime evidence untouched
baseline promotion artifacts restored byte-identical after every regeneration (sha256 verified)
```
