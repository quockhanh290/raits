# Audit — `lag1calm_pcloc_bottom_down_long_e1000_x1555__MES_MNQ__not_deep_gap`

Date: 2026-08-21 (machine clock: Calgary, MDT). Commit: `601970b`.
Contract: read-only. No production code touched, nothing committed.

Every number is my own measurement against local parquet and the saved logs.

---

## Verdict

**PAPER/PILOT ONLY.**

The look-ahead that killed the previous two Calm families is genuinely gone, and I could not
find a new one. The regime gate is causal and provably so, the signal uses only pre-10:00
information, the fills are feasible, there is no hidden stop, and the edge survives triple
cost. That is a real improvement and it is not a small one.

What stops it short of deploy-level is evidence weight, not correctness: the out-of-sample
confirmation rests on 29 trading days in a window that the Calm research program has already
scored 115 times, the pooled out-of-sample result does not clear zero, and two thirds of the
in-sample edge sits in the last two years.

---

## 1. Reproduction

All headline numbers reproduce exactly, including the gap filter recomputed independently
from 1-minute parquet rather than read from the artifacts.

| Window | Baseline MES+MNQ | not_deep_gap (gap >= -1.0%) | Dropped |
|---|---|---|---:|
| IS 2018-2024 | 366 / +$8,781 / PF 1.53 | **349 / +$9,718 / PF 1.67 / avg $27.85 / MaxDD $1,720** | 17 |
| 2025 | 48 / +$1,907 / PF 2.28 | **44 / +$2,050 / PF 2.69 / avg $46.58 / MaxDD $362** | 4 |
| 2026 YTD | 31 / +$914 / PF 1.36 | **29 / +$757 / PF 1.32 / avg $26.09 / MaxDD $445** | 2 |

The gap filter is exactly `current_rth_open / prior_rth_close - 1 >= -0.010`. Zero missing
gap values in any window.

### Fill audit counters

| Window | outside_exit_bar | outside_entry_bar | signal_after_entry |
|---|---:|---:|---:|
| IS 2018-2024 | 0 | 0 | 0 |
| 2025 | 0 | 0 | 0 |
| 2026 | 0 | 0 | 0 |

---

## 2. Regime causality — PASSES, and passes on its own merits

**Direct check.** For all 2,168 labelled days, the label the candidate uses equals the label
of the last SPY session **strictly before** that day. Zero mismatches. The lookup is
index-based over actual SPY sessions (`searchsorted`), not calendar arithmetic, so weekends
and holidays are handled correctly. On 91.2% of days the causal label happens to equal the
same-day label — that is regime persistence, not leakage; the remaining 8.8% is where the
two differ and the check above confirms the candidate always takes the earlier one.

**Mutation test.** Swapping the same-day label back in changes the result in every window,
which proves the two code paths are genuinely different:

| Window | D-1 causal (as specified) | Mutated to same-day D | Move |
|---|---:|---:|---:|
| IS | +$8,781, PF 1.53 | +$7,114, PF 1.46 | **-$1,667** |
| 2025 | +$1,907, PF 2.28 | +$2,071, PF 2.05 | +$164 |
| 2026 | +$914, PF 1.36 | +$119, PF 1.05 | **-$795** |

The sign matters. For the rejected negative-overnight and open-location families the
same-day label was worth roughly the entire result. Here the causal version is **better**
in-sample than the leaky one. This candidate is not harvesting the label look-ahead — it is
mildly hurt by it.

**The Calm gate is load-bearing, and it earns its place causally.** Same signal, same
instruments, same gap filter, sliced by D-1 regime:

| Gate | IS 2018-2024 | 2025 | 2026 |
|---|---|---|---|
| no regime gate | +$12,548 / 915 / avg $13.71 / PF 1.20 | +$11,777 / 103 | -$170 / 83 |
| **D-1 Calm (candidate)** | **+$9,718 / 349 / avg $27.85 / PF 1.67** | +$2,050 / 44 | +$757 / 29 |
| D-1 Normal | **-$4,963 / 503 / PF 0.89** | +$2,906 / 54 | -$1,355 / 55 |
| D-1 Stress | +$7,687 / 61 / PF 3.30 | +$6,821 / 5 | none |

The gate roughly doubles average dollars per trade in-sample and the days it excludes are
loss-making. Note in passing that D-1 Stress days are the highest per-trade slice in both IS
and 2025 — on 61 and 5 trades respectively, so this is an observation to log, not to act on.

---

## 3. Signal causality and fill feasibility — PASSES

Every signal input is complete before 10:00 on day D:

- `prev_close_loc` and `prev_rth_ret` come from a one-row shift of the per-instrument daily
  frame sorted by trading day. They describe the prior RTH session, closed at 16:00 on D-1.
- The gap uses the **open of the 09:30 bar** on day D against the prior RTH close. Known at
  09:30:00, thirty minutes before entry.
- No same-day high, low, close, return or realised volatility enters eligibility anywhere.
- The trading-day index rolls at 18:00, so evening bars are assigned to the next session and
  cannot contaminate an RTH range.

Entry is the **open** of the 10:00 bar; exit is the **open** of the 15:55 bar. Signal
timestamp is the 09:30 bar in every trade and is strictly earlier than the entry timestamp
in every trade.

**No hidden stop or target.** The words `stop`, `target`, `stop_px`, `exit_reason` and
`feasible_stop` do not occur anywhere in the generation source. The trade log has no exit
reason column. Exit price is the 15:55 bar open for every row without exception. This is a
time-exit-only path, and no theoretical fill is being counted.

---

## 4. Cost sensitivity — survives

Cost model confirmed from code: `commission_rt` $1.24 round-turn plus two sides of slippage
at the stated tick count, tick value $1.25 for MES and $0.50 for MNQ. Recomputed from points
rather than rescaled:

| Slippage | MES / MNQ round-turn | IS | 2025 | 2026 |
|---|---|---|---|---|
| 2 ticks/side | $6.24 / $3.24 | +$9,718, PF 1.67 | +$2,050, PF 2.69 | +$757, PF 1.32 |
| 3 ticks/side | $8.74 / $4.24 | +$9,123, PF 1.62 | +$1,967, PF 2.58 | +$707, PF 1.30 |
| 4 ticks/side | $11.24 / $5.24 | +$8,528, PF 1.57 | +$1,884, PF 2.47 | +$657, PF 1.27 |
| 6 ticks/side | $16.24 / $7.24 | +$7,338, PF 1.47 | +$1,718, PF 2.27 | +$557, PF 1.23 |

Pooled out-of-sample holds up too: +$2,806 at two ticks, +$2,274 at six. Triple slippage
costs about a quarter of the in-sample edge and does not threaten the sign. This is the
strongest single result in the audit.

---

## 5. Statistical robustness — this is where it falls short of deploy-level

### IS by year

| Year | Trades | Net | Share |
|---|---:|---:|---:|
| 2018 | 59 | +$274 | 2.8% |
| 2019 | 65 | **-$47** | -0.5% |
| 2020 | 22 | +$1,250 | 12.9% |
| 2021 | 64 | +$249 | 2.6% |
| 2022 | **4** | +$1,367 | 14.1% |
| 2023 | 58 | +$2,675 | 27.5% |
| 2024 | 77 | **+$3,950** | **40.6%** |

The `top_year_share <= 0.75` gate passes comfortably at 0.41, but it is measuring the wrong
thing. **2023 and 2024 together are 68% of the in-sample edge.** 2018, 2019 and 2021 combine
to +$476 over 188 trades — **$2.53 per trade, below the round-turn cost in both
instruments.** Three of the seven years are flat, one is negative, and 2022 contributes 14%
on four trades. The effective record is three contributing years plus a four-trade year.

### IS by instrument

| Instrument | Trades | Net | PF | Avg | Positive years |
|---|---:|---:|---:|---:|---|
| MES | 164 | +$2,730 | — | — | 5/7 (unfiltered: 170 / +$2,299 / PF 1.42 / $13.52) |
| MNQ | 185 | +$6,988 | — | — | 7/7 (unfiltered: 196 / +$6,482 / PF 1.59 / $33.07) |

MNQ carries 72% of the filtered in-sample net.

### 2025 out-of-sample

| Metric | Value |
|---|---|
| Trades / trading days | 44 / **29** |
| Net | +$2,050 |
| Bootstrap p05 / p50 / p95 | +$358 / +$2,047 / +$3,771 |
| P(net > 0) | 0.978 |
| Two-sided day-clustered p | **0.049** |
| By instrument | MES 26 / +$777, MNQ 18 / +$1,273 |
| Monthly | 6 of 8 months positive, best month $788 = 38% of the year |
| Top-5 days | **95% of the year's net** (top-3 = 67%) |
| Symmetric trim 5/5 | +$1,424 (still positive — not purely tail-driven) |

My bootstrap reproduces the reported one closely (reported p05 +$331 / p50 +$2,032 / p95
+$3,818).

### 2026 sanity

| Metric | Value |
|---|---|
| Trades / trading days | 29 / 21 |
| Net | +$757, PF 1.32 |
| Bootstrap p05 / p50 / p95 | **-$2,072** / +$755 / +$3,639 |
| P(net > 0) | 0.672 |
| Two-sided p | **0.661** |
| Monthly | 4 of 7 positive; January **-$947**, February +$860 (114% of the year) |
| By instrument | MES 14 / +$288, MNQ 15 / +$469 |

### Pooled out-of-sample

| Metric | Value |
|---|---|
| Trades / days | 73 / 50 |
| Net | +$2,806 |
| Bootstrap p05 | **-$510** |
| Two-sided p | **0.166** |

Adding 2026 to 2025 takes the result back across zero. Treating 2025 alone as primary and
2026 as sanity is a defensible protocol only if it was fixed in advance; the effect is that
the entire out-of-sample case rests on 29 trading days.

---

## 6. Selection discipline — the largest remaining concern

### 6.1 2025 has been scored 115 times by this research program

Each script individually does the right thing: rank on in-sample, freeze, then score
out-of-sample. But the program has not. Counting distinct variant and filter labels that
already have a 2025 number written to disk under `scratch/calm_*2025*.csv`:

**115 distinct labels.**

These are not 115 independent tests — many overlap heavily, and summary files list masks
that were never promoted. But the number is far from one, and the candidate's 2025 p of
0.049 carries no adjustment for any of it. With even 20 effectively independent looks you
would expect one at p < 0.05 by chance; with 115 labels the expected count of spurious
survivors is several.

Within this candidate's own lineage the search surface is at least 34 in-sample comparisons:
8 signal filters times 2 directions in the excavation, then 18 shape and gap masks, before
2025 was opened. The gap threshold itself was chosen among five specifications
(±0.5%, ±1.0%, >= -1.0%, <= +0.5%, and an in-sample 10th/90th percentile band).

This does not make the candidate wrong. It means 2025 can no longer function as the
arbiter, and a genuinely untouched window is needed.

### 6.2 The MYM exclusion rationale does not survive being applied to itself

The stated justification reproduces exactly: MYM averages $19.59 per trade less than
MES+MNQ, one-sided permutation p = 0.049 over 20,000 draws. It is in-sample only, which is
methodologically correct.

But running the identical test one level down:

| Comparison | Average difference | One-sided p |
|---|---:|---:|
| MYM vs MES+MNQ | -$19.59 / trade | **0.049** |
| **MES vs MNQ** | **-$19.55 / trade** | **0.112** |
| MES vs MNQ+MYM | -$5.25 / trade | 0.336 |

MES underperforms MNQ by essentially the same margin that MYM underperforms the pair — 4
cents apart. The only reason MYM's p is smaller is that its comparison group is larger. The
rule as applied is not "exclude instruments that underperform by $20 a trade"; it is
"exclude the one whose p happened to land under 0.05 given the group I chose to compare it
against". Applied consistently for one more round, it would next drop MES and leave an
MNQ-only sleeve.

I am not recommending that. I am saying the exclusion needs a stated principle that does not
re-derive itself differently each round — a minimum per-trade expectancy, or a liquidity or
tick-size argument that does not depend on realised P&L at all.

---

## 7. Defects found

### 7.1 Two definitions of "previous RTH day" coexist, and they disagree

The generation script builds its daily frame with the 18:00 trading-day rollover and
requires a 15:55 bar to exist. The shape and gap script builds its own daily frame by
calendar date with no such requirement. Half sessions have no 15:55 bar, so the first frame
drops them entirely and the second keeps them — which means the two disagree about which day
is "the previous RTH day" whenever a half session intervenes.

Measured disagreement in the gap value: **11 rows in-sample, 2 in 2025, 1 in 2026.**

In-sample and 2025 no trade crosses the -1.0% threshold as a result, so the reported numbers
are unaffected. In 2026 one trade flips:

| Day | Instrument | P&L | Gap (shape/gap path) | Gap (excavation path) |
|---|---|---:|---:|---:|
| 2026-01-20 | MNQ | **-$428.74** | -0.597% (kept) | -1.682% (dropped) |

2026-01-19 was Martin Luther King Day: RTH ran 09:30 to 12:59, 210 bars, no 15:55 bar. The
reported 2026 figure of +$757 uses the calendar-date chain and therefore includes that
loser; the generation script's own chain would give **+$1,185 on 28 trades**.

The reported number is the *more conservative* of the two, so nothing is inflated. But 56%
of the reported 2026 sanity result turns on which of two undocumented conventions is in
force, and the production spec must name one explicitly before this trades.

Related and deliberate-looking but never actually decided: because a half session has no
15:55 bar, the strategy never trades on one. That is correct for the exit. What was not
decided is that half sessions also vanish from the prior-day feature chain.

### 7.2 `signal_after_entry` still cannot fail

It is `1 if signal_ts > t1000`, where the signal timestamp is the first bar at or after
09:30 and the entry is the first bar at or after 10:00 on the same sorted frame. The second
is always at least the first, so the counter is a constant zero. The property it asserts is
true — I verified it independently — but the check has no path to red, the same pattern
already corrected in the other Calm probes. The entry and exit bar checks are likewise
near-tautological here, since both prices are read straight from the bar being checked.

None of these three counters would detect a regime-label problem, which is where the last
two families died. Causality of the gate needs its own assertion.

### 7.3 Prior-day staleness

3.5% of signal rows (38 of 1,101) have a prior surviving row more than one session back.
Not a look-ahead — the range is still entirely in the past — but "prior RTH day" is not
always the immediately preceding session.

---

## 8. Blockers to deploy-level, in order

1. **A window nobody has scored.** 2025 has 115 labels on it and 2026 does not clear zero.
   Until there is an untouched period, the out-of-sample case is 29 trading days with no
   multiplicity adjustment. Forward paper trading is the cheapest way to buy one.
2. **Pooled out-of-sample crosses zero** (+$2,806, p05 -$510, p = 0.166). 2026 alone is
   p = 0.66.
3. **Pin the prior-RTH-day convention** in a single place and regenerate, so the half-session
   question has one answer. State whether a half session counts as the prior day.
4. **Restate the MYM rationale** as a principle that does not re-derive itself, or accept
   that the same rule points at MES next.
5. **Restate the in-sample record honestly**: three contributing years plus a four-trade
   year, with 2023-2024 at 68% and 2019 negative. The `pos_years >= 5` gate passes but does
   not describe what happened.
6. **Give the causality of the gate its own assertion** that can fail, alongside the three
   bar-level counters.

## 9. Production-safe pilot spec

If it goes to paper on the strength of section 2 through 4, this is the spec I would hold it
to, with nothing left implicit:

- Regime: previous SPY **session** label equals Calm, looked up by session index, never by
  calendar offset. Never the same-day label.
- Instruments: MES and MNQ, one micro each, no MYM.
- Direction: LONG only.
- Signal, all evaluated from data complete before 10:00 ET on day D: prior RTH close in the
  bottom third of the prior RTH range; prior RTH session was a down day (close below open);
  and `today_0930_open / prior_rth_close - 1 >= -0.010`.
- "Prior RTH day" must be a single named convention. Recommend the stricter one — the
  session must be a full session with a 15:55 bar — so that the same rule governs both the
  feature and the tradability of the day.
- Entry: market at the 10:00 bar. Exit: market at the 15:55 bar. No stop, no target.
- Maximum two concurrent positions (one per instrument), no pyramiding, no re-entry after a
  restart within the same session.
- Cost assumption to carry into the pilot: 4 ticks per side, not 2 — the sleeve survives it
  and the pilot should be sized against the pessimistic case.
- Record actual fill timestamps and realised slippage at 10:00 and 15:55 for every trade.
  That is the measurement the pilot exists to produce.
- Interaction with the Normal core and Stress hedge is unmeasured here by design. Before any
  combined run, note that this sleeve is long index futures intraday and the Stress hedge is
  short index futures intraday; on a D-1-Calm day that turns stressful they can both be open.
  That netting question needs answering before capital, not after.

Not deploy-level. Not rejected. Paper it, on a window nobody has looked at.

---

# 10. REPAIR VERIFICATION — 2026-08-21

My own measurement at the current working tree, not taken from the repair note.

## 10.1 The repair works

The two prior-session chains now agree completely. Comparing the shape/gap frame against
the excavation's own daily frame, row by row:

| Window | Rows compared | Gap values still differing |
|---|---:|---:|
| IS 2018-2024 | 366 | **0** |
| 2025 | 48 | **0** |
| 2026 | 31 | **0** |

`prev_session_day` is present and correct. Two rows appeared to disagree on it in 2026 —
2026-01-02 for both instruments — but that is an artifact of **my** comparison, not of the
code: the excavation frame's shift happens after the start-date filter, so its first
returned row carries a null prior day while the shape/gap frame reaches back into December.
No real disagreement. Reporting it as a finding would have been a fabrication.

## 10.2 Post-repair numbers reproduce

| Window | Trades | Net | PF | MaxDD | Audit |
|---|---:|---:|---:|---:|---|
| IS 2018-2024 | 349 | +$9,718 | 1.67 | $1,720 | 0/0/0 |
| 2025 OOS | 44 | +$2,050 | 2.69 | $362 | 0/0/0 |
| 2026 sanity | 28 | +$1,185 | 1.61 | $385 | 0/0/0 |
| Pooled sanity | 72 | +$3,235 | 2.02 | — | 0/0/0 |

Pooled bootstrap over 49 trading days: p05 **+$44**, p50 +$3,231, p95 +$6,481,
P(net > 0) = 0.952, two-sided p = **0.099**. The repair note reports p05 +$53; the gap is
seed noise and the conclusion is identical.

IS and 2025 are unchanged, as stated.

## 10.3 Two things the improvement should not be read as

**The 2026 gain is not new evidence, and the responsibility for that is mine.** I
recommended the stricter convention in section 8 *after* having already measured, in section
7.1, that it moves 2026 from +$757 to +$1,185 by dropping one losing trade. The principled
argument stands on its own — a session with no 15:55 bar cannot be exited by this strategy,
so it should not be a tradable day *or* a prior-session source, and one rule should govern
both. But I knew the direction when I made the recommendation. A convention chosen with its
effect visible does not produce independent confirmation. The honest reading of 2026 is:
substance unchanged, one known loser removed by a rule selected knowing it would be removed.

**The pooled p05 is on the line, not above it.** +$44 out of +$3,235 means the fifth
percentile is sitting essentially at zero, and the two-sided p of 0.099 does not clear
conventional significance. And the entire move from the pre-repair p05 of -$510 to +$44 is
the removal of that single -$429 trade. Quoting "bootstrap p05 +$53" without this context
reads as confirmation; it is a distribution whose lower tail still touches zero on 49 days.

## 10.4 Blocker status

| # | Blocker | Status |
|---|---|---|
| 1 | A window nobody has scored (2025 carries 115 labels) | **OPEN** |
| 2 | Pooled out-of-sample clears zero | **OPEN** — p05 +$44, p = 0.099, and the move came from the convention change, not new data |
| 3 | Pin the prior-RTH-session convention | **CLOSED** — verified above |
| 4 | MYM rationale that does not re-derive itself (MES vs MNQ is -$19.55/trade at p = 0.112 against MYM's -$19.59 at p = 0.049) | **OPEN** |
| 5 | Restate the IS record as three contributing years plus a four-trade year; 2023-2024 = 68%, 2019 negative | **OPEN** |
| 6 | An assertion on gate causality that can actually fail | **OPEN** |

Verdict unchanged: **PAPER/PILOT ONLY**. One of six blockers closed, and it was the one a
code change could close. The remaining five are about evidence and about how the record is
stated, and no further code change will move them — only an untouched window will.
