# Stage 5ZZZ-K — can ES intraday at 14:00 recover the same-day regime label?

**Route:** `track1_candidate` · **Date:** 2026-08-29 · Label-recovery test only — no backtest, no promotion
**Orders:** never enabled, still impossible

## Decision

# `ES_PROXY_NOT_PROMISING`

ES fixed the data problem and did not fix the idea. Coverage is essentially complete in all three windows — but the proxy loses to plain persistence **in every one, including both out-of-sample windows**, and it degrades Normal detection in exactly the direction that would hurt a Normal-only sleeve.

| | D-1 persistence | ES pre-14:00 proxy | difference |
|---|---:|---:|---:|
| floor 2018-2024 *(in-sample)* | **91.5%** | 81.9% | **−9.6 pts** |
| **2025 OOS** | **87.6%** | 82.4% | **−5.2 pts** |
| **2026 OOS** | **87.3%** | 75.9% | **−11.4 pts** |
| all sessions | **90.6%** | 81.4% | **−9.2 pts** |

The promotion bar's first clause — *must beat D-1 agreement OOS, not only in-sample* — fails in both OOS windows. No backtest is warranted.

---

## 1. Data: ES covers all three windows

`data/cache/futures/ES_continuous_1m_8y.parquet` — 3,375,148 bars, 2017-01-02 → 2026-08-28.

| Window | sessions with a usable 14:00 ET bar | expected | coverage | HMM fit end |
|---|---:|---:|---:|---|
| floor 2018-2024 | 1,736 | ~1,763 | **98.5%** | 2022-12-31 |
| 2025 OOS | 250 | ~251 | **99.6%** | 2024-12-31 |
| 2026 OOS (to 08-19) | 158 | ~158 | **100.0%** | 2024-12-31 |

This is the one thing SPY could not do — Stage 5ZZZ-J found zero SPY intraday sessions in 2025 or 2026. So the coverage clause of the promotion bar passes, and the test could finally be run out-of-sample.

### Timezone, measured rather than assumed

The parquet index is **naive UTC**. This repo has already paid for two loaders disagreeing about a clock, so it was settled by measurement instead of by reading:

```text
localise UTC  -> ET volume peaks at hours [15, 10, 9, 11],  RTH share 80.3%
localise ET   -> ET volume peaks at hours [14, 19, 15, 16], RTH share 42.6%
```

UTC puts the mass inside the session with the peak in the closing hour, which is what ES actually does. The two tz-aware frozen copies agree at 80.2% and 80.5%.

---

## 2. The proxy is causal

Features, all closed by **14:00 ET** on the session being labelled:

```text
gap                 open(09:30) / previous RTH close - 1
ret_to_1400         close(14:00) / previous RTH close - 1
ret_open_to_1400    close(14:00) / open(09:30) - 1
range_to_1400       (high - low, 09:30-14:00) / previous RTH close
overnight_range     (high - low, 18:00 prior -> 09:30) / previous RTH close   <- ES only
rvol_1400           realised vol of 1-minute returns, 09:30-14:00
vol_ratio           volume to 14:00 / trailing 20-session median, SHIFTED
rvol_5d_prior       5-session mean of rvol_1400, SHIFTED
absret_5d_prior     5-session mean of |ret_to_1400|, SHIFTED
```

The 16:00 close of the predicted session is never read. `overnight_range` is genuinely new information SPY cannot supply — the 18:00-to-09:30 futures session — and it is closed before the RTH open.

**Walk-forward:** refit every 126 sessions on everything strictly before; the first ~18 months are warm-up with no prediction. The 2025 and 2026 predictions come from models that never saw them. Labels follow the route's own convention — floor from the fit through 2022-12-31, 2025/2026 from the fit through 2024-12-31 — so no later fit leaks backwards.

---

## 3. Where the accuracy goes

Same shape in every window: it repairs about half of persistence's mistakes and breaks far more of its successes.

| Window | D-1 wrong | proxy fixes | D-1 right | proxy breaks | **net** |
|---|---:|---:|---:|---:|---:|
| floor | 115 | 58 (50.4%) | 1,243 | 189 (15.2%) | **−131** |
| 2025 | 31 | 13 (41.9%) | 219 | 26 (11.9%) | **−13** |
| 2026 | 20 | 13 (65.0%) | 138 | 31 (22.5%) | **−18** |

2026 is the sharpest illustration: the proxy is the *best* it ever gets at repairing D-1 (65% of its 20 errors) and still finishes 11.4 points behind, because it broke 31 of the 138 days persistence already had right.

---

## 4. Normal detection — the question that matters for Swing

Swing trades `Normal` and nothing else, so this is the state to judge on.

| Window | | D-1 precision | D-1 recall | proxy precision | proxy recall |
|---|---|---:|---:|---:|---:|
| floor | Calm | 0.918 | 0.919 | 0.819 | 0.870 |
| | **Normal** | **0.918** | **0.917** | **0.839** | **0.803** |
| | Stress | 0.874 | 0.874 | 0.654 | 0.609 |
| 2025 | Calm | 0.902 | 0.894 | 0.905 | 0.761 |
| | **Normal** | **0.863** | **0.871** | **0.765** | **0.897** |
| | Stress | 0.809 | 0.809 | 0.842 | 0.762 |
| 2026 | Calm | 0.859 | 0.859 | 0.941 | **0.500** |
| | **Normal** | **0.889** | **0.889** | **0.710** | **0.978** |
| | Stress | 0.750 | 0.750 | — | **0.000** |

**Normal precision falls in every window** — by 8, 10 and 18 points. In the two OOS windows the proxy buys a little Normal *recall* by giving up a lot of Normal *precision*, and for a Normal-only sleeve that is the worst available trade: it fires on more sessions, and a larger share of those sessions are not Normal.

The 2026 confusion makes it concrete:

```text
proxy said Normal on 124 sessions:  88 really Normal · 32 really Calm · 4 really Stress
proxy said Stress on   0 sessions:  it never predicted Stress at all
Calm recall collapsed to 0.500
```

Under this proxy the sleeve would have traded **32 Calm sessions it should have sat out**, inside a single eight-month window — and Calm/Stress separation is not preserved, it is gone. That fails the promotion bar's second clause as squarely as the accuracy fails its first.

---

## 5. Answers

| question | answer |
|---|---|
| ES intraday covers all windows | **Yes** — 98.5% / 99.6% / 100.0% |
| D-1 agreement vs ES proxy | **90.6%** vs **81.4%** overall |
| floor | 91.5% vs 81.9% (**−9.6**) |
| 2025 OOS | 87.6% vs 82.4% (**−5.2**) |
| 2026 OOS | 87.3% vs 75.9% (**−11.4**) |
| Does it improve Normal detection | **No.** Precision −0.080 / −0.098 / −0.179; the OOS recall gain is bought with a larger precision loss |
| Worth a full Track 1 backtest next | **No.** It fails the first promotion clause in both OOS windows |
| `orders_possible` | **False** — `PAPER_SHADOW_EVIDENCE` |

Swing remains where the operator put it: enabled in shadow, not paper-orderable. No live route code changed; this stage was read-only over data.

---

## 6. What this now closes, and what it does not

Two instruments have now been tested and both lose to persistence by a similar margin — SPY 82.8% against 91.6% on the floor, ES 81.9% against 91.5% on the same window. The agreement between two independent measurements is itself informative: **the limit is not the instrument.**

The mechanism was stated in Stage 5ZZZ-J and this stage did not dent it. The target is *defined* by the 16:00 close, so a 14:00 vantage is two hours short by construction; and the label is extremely persistent, so yesterday's answer is a very strong baseline that intraday movement degrades rather than sharpens. Adding the overnight session — real information SPY does not have — moved nothing.

**What is not closed.** This is one model class over nine features at one cut time. A different formulation could score differently, and three things would be worth trying before anyone calls the idea dead rather than merely unpromising:

- **A later cut.** 14:00 was chosen because Swing starts at 14:05. A 15:30 or 15:55 cut would be much closer to the close and would still be causal for a *later* sleeve — but not for this one.
- **Predicting the sleeve's outcome instead of the label.** The label is a means, not the end. A model that predicts whether a Swing entry would have worked skips the two-hour gap entirely.
- **A precision-weighted objective.** This model maximises overall accuracy. A Normal-only sleeve cares about Normal *precision*, and a model tuned for it would trade recall away deliberately rather than by accident.

None of those is authorised here, and none should be run as a backtest first — each is a label-recovery or outcome-recovery test that costs minutes, which is what this stage and the last one both demonstrated is the right order.

## Safety

```text
orders_possible False · blocking ['PAPER_SHADOW_EVIDENCE'] · scheduler pid 3000, not restarted
no broker call · orders dir ABSENT · TRACK1_ORDERS_APPROVED unset · confirmation intact
no live route code changed · runtime evidence untouched · read-only over data
```

### A tooling failure worth recording

The probe's first run reported **zero usable sessions in all three windows**. That is not a data finding, it is an empty result, and the rule is to suspect the instrument before believing it. The cause was the overnight-session join: grouping on `.values` stripped the timezone, so every reindex against the tz-aware session index produced NaN and the final `dropna` emptied the frame. Fixed, and the probe now carries two assertions that make the same failure loud instead of quiet — one on the overnight join and one on the feature/label intersection.
