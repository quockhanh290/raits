# Independent audit — Calm sleeve candidate `on_neg_fade_mod001_010_x1555`

Date: 2026-08-21 (machine clock: Calgary, MDT). Commit at audit: `601970b`.
Contract: read-only. No production code changed, nothing committed.
Re-runnable evidence script: `scratch/audit_calm_negon_20260821.py`
Saved output: `scratch/audit_calm_negon_20260821.txt`

Every number below came from my own measurement, not from the research document
or from any agent report.

---

## 0. Measurement basis

| Item | Value |
|---|---|
| Trade logs read | `scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_{is,2025,2026}.csv` |
| Bars re-read | `data/cache/futures/frozen_sim`, `frozen_2025_sim`, `data/cache/futures` (1-minute, ET) |
| Cost model reconstructed | commission $1.24 round-turn + 2 sides x 2 ticks x tick value → MES $6.24, MNQ $3.24, MYM $3.24 |
| Headline reproduced | IS 699 trades +$14,850 PF 1.60 · 2025 87 +$2,736 PF 1.54 · 2026 63 +$2,634 PF 1.58 |

The headline numbers reproduce exactly from the saved trade logs. Two independent
implementations of the same sleeve — the sweep (which reads Calm days from a CSV) and the
deploy probe (which re-derives Calm days from the HMM) — agree on 699 / 87 / 63 trades.
That is a real cross-check and it passes.

---

## 1. What I verified as CLEAN

These were checked and are correct. Reporting them separately so the findings list below
is not read as "everything is broken".

**The entry price is genuinely the open of the 09:30 bar.** I re-read every bar from the
parquet and compared. Mismatches: 0 of 699 (IS), 0 of 87 (2025), 0 of 63 (2026).

**The exit price is genuinely the open of the 15:55 bar, and it is not the close.** Zero
mismatches against the bar open in all three windows. This check can fail: 673 of 699 exit
bars have an open different from their close, and rerunning the sleeve on the close instead
gives +$15,231 rather than +$14,850. So the "open, not close" claim is a measured property,
not a definition that could not have come out wrong.

**No trade leaves the day.** Exit timestamp is after entry in every trade; exit date equals
entry date in every trade; the signal timestamp equals the entry timestamp in every trade.

**The overnight window is assigned to the right trading day and contains no future.** The
day grouping rolls the session at 18:00 ET, so the return is computed from the previous
evening's 18:00 open to the 09:29 close — entirely before the 09:30 entry.

**Band membership is exact.** Every trade's overnight return lies inside (-1.0%, -0.1%];
zero violations in all three windows.

**The SPY short filter on the Normal core does not leak.** Both the previous close and the
50-day average are shifted one session back before comparison.

**The Normal core matches the config it is described as.** Normal-only trend follow, EMA
switched 30 → 50, 2x daily ATR stop basis, corrected/live fill with the 14:05 arming
convention, ratchet off, shorts only when SPY closed below its 50-day average the prior
session. The `roska4_only=False` setting, which extends the fix bundle to NKD, is the same
in every sibling research probe — it is a convention of this research line, not an accident.

**The deploy probe's fill audit is a real audit.** It re-reads the bar and requires the
recorded exit price to lie inside that bar's high/low range. It can fail, and it did fail —
it caught genuine impossible stop exits in the NKD leg (3 in the floor window, 1 in 2026).
That failure is honestly recorded in the research document.

**Data vintage differences do not matter here.** The in-sample window runs on the frozen
parquet while 2026 runs on the live cache. I repriced all 699 in-sample trades on the live
cache: only 12 trades differ at all, for a net effect of -$17. (Side note: 14 of those 699
trade bars are missing entirely from the live cache — a data-completeness gap in the live
cache, not an error in the reported numbers.)

**The ATR look-ahead is real in mechanism but immaterial in size.** The daily ATR used for
risk normalisation is read "as of" the trade day, and the daily bar for that day already
includes the day's own range. Re-measuring with an ATR that stops at the prior session moves
the 95th-percentile adverse excursion from 1.036 to 1.063 ATR (in-sample), 1.104 → 1.119
(2025), 1.012 → 1.050 (2026). Not a blocker.

---

## 2. Critical blockers

### C1 — The edge lives inside the first minute after the open, and nothing shows you can capture it

The signal is complete at the 09:29 close and the fill is taken at the 09:30 open print.
That is a zero-latency assumption: the model computes the overnight return from a bar that
has just closed, and buys at the first tick of the next bar.

I delayed the entry to the open of a later minute and re-priced the same trades:

| Window | Base | Entry +1 min | Entry +2 min | Entry +5 min |
|---|---:|---:|---:|---:|
| 2018-2024 | +$14,850 | +$14,121 (-4.9%) | +$13,833 (-6.8%) | +$13,137 (-11.5%) |
| 2025 | +$2,736 | +$2,535 (-7.4%) | +$2,422 (-11.5%) | +$2,373 (-13.3%) |
| 2026 | +$2,634 | +$2,049 (**-22.2%**) | +$1,942 (-26.3%) | +$1,144 (-56.6%) |

One minute of latency removes roughly a fifth of the 2026 result. Five minutes removes more
than half. The exit is not fragile in the same way — delaying the exit one minute actually
*adds* $351 in-sample and $397 in 2025 — so this is specifically an entry-timing exposure.

The opening minute is also the minute where the micro book is thinnest and the spread is
widest, which is exactly where the flat 2 ticks per side is least likely to hold. Nothing in
the record tests a wider open-specific slippage assumption, a limit-order variant, or a
measured fill quality at 09:30:00.

**Why this blocks production:** the sleeve's advertised return is conditional on a fill the
system has never demonstrated it can obtain, in the one minute of the session where that
assumption is weakest.

### C2 — The Calm sleeve cap cannot limit concurrent positions; it is structurally inert

The portfolio replay realises a trade on the day it exits, and only appends a position to
the open book when it survives past that day. Every Calm trade opens and closes on the same
day (verified above), so **no Calm position is ever in the open book when the next Calm
trade is admitted**. The cluster budget therefore only ever sees the single proposed trade.

Consequence: the "Calm own cap" and the "Calm relaxed cap" are the same policy for
concurrency purposes. Whatever the cap number, three Calm micros can fire on the same day,
every day, and no cap sees the second or third one.

This is not hypothetical. The distribution of concurrent instruments per Calm day:

| Window | 1 instrument | 2 instruments | 3 instruments |
|---|---:|---:|---:|
| 2018-2024 | 106 days | 70 days | **151 days** |
| 2025 | 22 | 10 | 15 |
| 2026 | 14 | 8 | 11 |

Three-at-once is the single most common state in-sample.

The three 2026 rejections that the research document attributes to the Calm cap are
something else entirely. The admission proxy is one daily ATR times point value for a single
micro. Measured against the 2.5% cap ($1,250 on a $50,000 account):

| Window | MES max | MNQ max | MYM max | Trades over $1,250 |
|---|---:|---:|---:|---|
| 2018-2024 | $363 | $800 | $279 | 0 of 699 |
| 2025 | $550 | $1,127 | $330 | 0 of 87 |
| 2026 | $515 | **$1,341** | $360 | **3 of 20 MNQ trades** |

So the cap is acting as a per-trade volatility filter on high-ATR MNQ days, not as a sleeve
limit. Relaxing it admits exactly those three trades, which happened to be worth +$433 — and
the research document reads that as evidence for relaxing the cap. That is choosing a risk
policy by the profit of the three trades it excludes.

The "max 2-3 concurrent" policy has been *measured* as a research proxy (max 2 → +$11,576,
max 1 → +$6,281, versus +$14,850 unconstrained) but is **not implemented anywhere in the
deploy path**.

### C3 — The fill audit that all the sweep and profile artifacts print is a constant

In `scratch/calm_neg_overnight_exit_sweep.py:114`, `calm_neg_overnight_mae_profile.py:111`,
`calm_neg_overnight_risk_filter_probe.py:81-82` and `calm_candidate_deploy_probe.py:274`,
the `outside_exit_bar` field is written as the literal `0`. Every downstream report then
sums that column and prints `outside_exit_bar=0`.

Two gates depend on it and therefore cannot ever fail:

- `calm_neg_overnight_wfo_stability.py:51` — the WFO eligibility test requires
  `outside_exit_bar` to sum to zero.
- `calm_neg_overnight_risk_filter_probe.py:239` — the candidate-selection filter requires
  the same.

`signal_after_entry` does not exist at all in those four scripts; it only exists in the
deploy probe, where it is computed properly.

The underlying construction happens to be sound — I proved that independently in section 1
by re-reading the bars. But the number the reports print as evidence is not evidence. Any
future change to the exit logic would keep printing `outside_exit_bar=0` while silently
becoming infeasible. This is the same defect family already paid for elsewhere in this
repository: a check that prints green and has no path to red.

---

## 3. High-risk concerns

### H1 — The overnight-return band inverts out of sample

The band (-1.0%, -0.1%] was chosen on 2018-2024. Breaking the unfiltered variant into
buckets shows what each boundary is doing:

| Overnight bucket | In band? | 2018-2024 | 2025 | 2026 |
|---|---|---:|---:|---:|
| -2% to -1% | no | +$1,499 (28 trades) | +$849 (4) | +$0 (4) |
| -1% to -0.5% | **yes** | +$6,930 (138) | **-$862 (18)** | **-$316 (22)** |
| -0.5% to -0.2% | **yes** | +$7,453 (323) | +$2,685 (39) | +$2,726 (26) |
| -0.2% to -0.1% | **yes** | +$467 (238) | +$914 (30) | +$224 (15) |
| -0.1% to 0% | no | -$1,144 (309) | **+$1,700 (41)** | -$195 (9) |

Both boundaries flip. The bucket just below the upper cut was the reason for the cut
in-sample (-$1,144) and is one of 2025's better buckets (+$1,700). The bucket just above the
lower cut is the best per-trade bucket in-sample and is thrown away. And the largest
included bucket, -1% to -0.5%, contributed +$6,930 in-sample and is **negative in both
out-of-sample years**.

The only bucket that is positive and substantial in all three windows is -0.5% to -0.2%.
I am deliberately not proposing that as a new band — refitting a threshold on the windows
that broke the old threshold is the same mistake one level deeper. The point is that the
band's boundaries carry no stable behaviour, which is what a fitted parameter looks like.

### H2 — The walk-forward chose a different variant, and was overridden after seeing out-of-sample

The rolling folds in the research record select:

| Train | Test | Selected | Test trades |
|---|---|---|---:|
| 2018-2021 | 2022 | `mod001_010_x1555` | **2** |
| 2019-2022 | 2023 | `raw_x1555` | 159 |
| 2020-2023 | 2024 | `raw_x1555` | 207 |

The walk-forward picks the unfiltered variant in the two folds that have a usable sample.
It picks the candidate only in the fold that tests on two trades.

The stated reason for overriding it is the 2024 fold and drawdown. Measured: in-sample
maximum drawdown is $2,216 for the unfiltered variant versus $1,881 for the candidate — a
$335 difference, 0.67% of a $50,000 account. Against that, the unfiltered variant earns
+$5,285 in 2025 against the candidate's +$2,736, and my day-clustered bootstrap gives it a
stronger 2025 signal (p=0.082 versus p=0.252).

Two further selection-order problems in the same decision:

- The research text justifies the choice with "lower 2025 dollars" for the backup variant.
  That is a 2025 figure used to rank candidates, after 2025 was supposed to be sealed.
- The backup variant's out-of-sample numbers (2025: 57 trades +$1,822; 2026: 48 +$2,410)
  are **not in the saved sweep outputs at all** — the sweep only carried the two in-sample
  selections forward. Those numbers came from a second, separate pass at the out-of-sample
  data after the first pass had been seen.

### H3 — Out-of-sample confidence intervals contain zero

I ran a bootstrap that resamples **trading days**, not trades, because up to three
instruments fire on the same signal on the same day and their outcomes are not independent.
5,000 draws, two-sided p against a centred null:

| Window | Days | Net | 95% interval | p |
|---|---:|---:|---|---:|
| 2018-2024 | 327 | +$14,850 | [+$5,549, +$24,107] | 0.0008 |
| 2025 | 47 | +$2,736 | [-$2,217, +$7,615] | 0.252 |
| 2026 | 33 | +$2,634 | [-$2,119, +$7,654] | 0.293 |
| **2025+2026 pooled** | **80** | **+$5,371** | **[-$1,777, +$12,264]** | **0.125** |

This agrees with the bootstrap already in the research record (its daily probability of a
positive 2025 was 0.861; mine implies about 0.874).

Following this project's own labelling rule, p=0.125 is *insufficient evidence*, not
evidence of no edge. But it means the out-of-sample record is not a confirmation of the
in-sample result — it is 80 trading days that are consistent with the in-sample result and
also consistent with nothing.

### H4 — Out of sample, one instrument carries the sleeve

Pooling 2025 and 2026:

| Instrument | Trades | Net | 95% interval | p | Median trade |
|---|---:|---:|---|---:|---:|
| MNQ | 51 | +$3,797 | [-$860, +$8,255] | 0.114 | +$97.26 |
| MES | 43 | +$1,290 | [-$677, +$3,282] | 0.193 | +$45.01 |
| MYM | 56 | +$284 | [-$1,330, +$1,903] | 0.728 | **-$5.99** |

MNQ is 71% of pooled out-of-sample dollars. The in-sample instrument split is genuinely
balanced (MES +$4,698, MNQ +$6,012, MYM +$4,140), so the "not one-instrument-only" check
passes in-sample and fails out-of-sample.

On MYM specifically: the stated reason for keeping it is that in-sample and 2026 are
positive and it diversifies away from MNQ. Measured, MYM's entire out-of-sample contribution
is +$284 over 56 trades — about $5 per trade against a $3.24 round-turn cost — with a
negative median trade. That is not an argument to drop it (nor to keep it) on its own; it is
an argument that MYM's out-of-sample edge has not been demonstrated at all, and the
diversification claim should be stated as an assumption rather than a measured result.

### H5 — The seven-year in-sample record is really five and a half years

| Year | Calm days with any negative overnight | Candidate trades | Net | Share |
|---|---:|---:|---:|---:|
| 2018 | 73 | 127 | +$2,276 | 15.3% |
| 2019 | 77 | 128 | +$3,424 | 23.1% |
| 2020 | 43 | 63 | +$478 | 3.2% |
| 2021 | 87 | 121 | +$2,960 | 19.9% |
| **2022** | **2** | **2** | +$171 | 1.1% |
| 2023 | 66 | 118 | +$3,766 | 25.4% |
| 2024 | 98 | 140 | +$1,776 | 12.0% |

2022 is not a positive year — the regime model labelled essentially nothing in 2022 as Calm,
so the strategy did not exist that year. Counting it toward "7 of 7 positive years" and
toward the "at least 5 positive years" robustness gate inflates both. 2020 adds 3.2%.
The real record is five contributing years.

The same fact makes the first walk-forward fold uninformative: it tests on two trades.

---

## 4. Medium and low concerns

### M1 — Drawdown is measured on realised cash only

Portfolio metrics build the equity curve from daily realised profit and loss; multi-day
swing and NKD positions contribute nothing until they close. Adding a sleeve that realises a
small positive amount on most days mechanically smooths that curve. The reported Calm
contribution of +0.42 Calmar and -2.5 points of maximum drawdown is therefore partly a
property of the measurement frame, not only of the sleeve. A mark-to-market equity curve
would be the apples-to-apples comparison.

### M2 — Regime labels for 2018-2022 come from a model fitted through 2022

The regime model is fitted once on data through 2022-12-31 and then used to label every day
from 2018 onward. Labels for 2023-2024 and for both out-of-sample years are clean; labels
for 2018-2022 are not reproducible in real time. That span carries 62.7% of in-sample
dollars ($9,308 of $14,850). This is a documented, deliberate decoupling rather than an
accident, but it should be stated wherever the in-sample figure is quoted.

The same thing makes the first walk-forward fold doubly weak: its test year sits inside the
label-fitting window as well as having two trades.

### M3 — The half-at-noon variant is not executable and undercharges cost

In `calm_neg_overnight_risk_filter_probe.py:195`, the split variant averages the noon price
and the 15:55 price and charges **one** round-turn. Two exits cost two round-turns. And with
micro contracts there is no half position to exit — the file's own comment says so. The
variant should not sit in a table that ranks candidates against the chosen one.

### M4 — Correcting the brief: the wide disaster stops HAVE been tested

The brief says 1.5x and 2.0x daily ATR disaster stops are still missing. They are not:
`scratch/calm_sleeve_validation.py:511-513` tests 1.25x, 1.5x and 2.0x, and the results are
in the research record.

The result is the finding. At 1.5x, roughly 1% of in-sample trades are stopped and 2025 and
2026 are bit-identical to no stop at all. At 2.0x, nothing is stopped in any window. So the
"disaster stop" that is being proposed for production **has never fired in nine years of
data**. Its measured protection is zero because there is no observation of it working. If it
ships, it ships as an unexercised code path — the stop-placement logic, the arming, the
cancellation on time exit, and the interaction with the 15:55 exit will all run for the
first time in live trading.

### M5 — Correcting the record: the sleeve is not outlier-driven

The research record reports "2025 top-5 trades are 81.6% of net; 2026 top-5 are 100.2%" and
reads it as outlier sensitivity. That statistic is arithmetically inevitable here: net is a
small residual of two large gross sides (2026: +$7,204 of wins against -$4,569 of losses for
a net of +$2,634), so any five trades will be a large fraction of the residual.

The symmetric test says the opposite. Removing the five largest winners **and** the five
largest losers:

| Window | Net | Trim 5/5 | Trim 10/10 | Median trade |
|---|---:|---:|---:|---:|
| 2018-2024 | +$14,850 | +$14,631 | +$14,120 | +$19.76 |
| 2025 | +$2,736 | +$2,806 | +$2,668 | +$35.76 |
| 2026 | +$2,634 | +$2,671 | +$2,204 | +$45.01 |
| OOS pooled | +$5,371 | **+$5,477** | +$4,872 | +$40.38 |

Trimming both tails leaves the result essentially unchanged, and in the pooled
out-of-sample case slightly higher. The median day is positive in every window (+$40.78,
+$62.53, +$46.76) with 54-60% positive days. The sleeve's problem is sample size and
selection discipline, not a handful of lucky trades. The research document should be
corrected on this point — it currently understates the sleeve on a statistic that does not
mean what it appears to mean.

### M6 — A label error in the research record

The record reports "p05 MAE -1.04 ATR". The profile script computes the 95th percentile of a
positive-magnitude adverse excursion. It is p95, not p05. Small, but it is the number the
whole stop-sizing discussion rests on.

### M7 — No event or macro calendar exists

Confirmed by search across the repository: there is no economic calendar, no FOMC or CPI
date table, no earnings calendar. Event filtering is not merely unimplemented — the data to
implement it is not present. Every macro-day claim about this sleeve is currently untested,
in both directions.

---

## 5. Live-readiness blockers not yet addressed

The sleeve exists only in `scratch/`. Nothing in `global_index/`, `futures/`, `raits/` or
`monitor/` references it. That is appropriate for its stage, but it means none of the
following has an implementation to audit:

- **Missed 15:55 bar.** The research code takes the first bar at or after 15:55 and skips
  the day entirely if none exists. Live, a missed 15:55 has to become an actual decision:
  exit at market on the next print, hold to the close, or hold overnight. There is no
  overnight risk model for this sleeve because it has never held overnight.
- **Duplicate signals.** Three instruments fire from one shared signal. A restart between
  09:30 and 15:55 must not re-enter.
- **State persistence.** The sleeve holds an open position for six and a quarter hours with
  no stop by default. A process restart in that window must recover the position, its entry
  price, and its scheduled exit.
- **Partial fills.** One micro per instrument makes partials unlikely, but if the sleeve
  ever sizes above one contract the 09:30 fill is the worst place for a partial.
- **Order type at the open.** Related to C1 — market-on-open, market at 09:30:00, and a
  marketable limit give materially different fills in the minute the edge lives in.

---

## 6. Questions and assumptions

1. **Was the final band chosen before or after 2025 was opened?** The sweep script's own
   selection routine ranks in-sample first and then scores out-of-sample, which is correct.
   But the research text ranks the three finalists using 2025 dollars, and the backup
   variant's out-of-sample figures are absent from the saved sweep outputs. I read that as a
   second pass at out-of-sample data. If there is a record showing the three finalists were
   frozen before 2025 was ever scored, that changes H2 materially and I would withdraw it.

2. **Is the 09:30 open print obtainable?** I assumed it is not, without evidence either way.
   A single day of live or paper timestamped fills at 09:30:00 on all three micros would
   settle C1 in one session.

3. **Is the Calm day universe identical between the two implementations?** They agree on
   trade counts (699 / 87 / 63), which is strong but not proof of identical day sets. I did
   not enumerate both sets.

4. **What is the mechanism?** The record describes what the filter does but not why a
   modest overnight decline in a Calm regime should be bought at the open and sold at 15:55.
   Without a mechanism, H1's bucket instability has no way to be adjudicated: there is no
   prior that says which buckets *should* work.

---

## 7. Verdict

**Research-confirmed but not production-ready.**

What is confirmed: the execution mechanics are real. Entry and exit prices are the bar opens
they claim to be, verified against the bars themselves with a test that can fail. There is
no lookahead in the signal, the trading-day assignment, the band, or the SPY filter. Costs
match the stated two ticks per side. The in-sample result is statistically strong
(p=0.0008), it survives trimming both tails, and it is not carried by a single instrument or
a single year in-sample.

What is not confirmed: that any of it generalises. The band's boundaries invert
out-of-sample, the walk-forward preferred a different variant and was overridden after
out-of-sample was seen, the out-of-sample interval spans zero, and out-of-sample dollars
come 71% from one instrument.

Before any capital:

1. Settle whether the 09:30 open fill is obtainable. Until then, treat +$2,049 rather than
   +$2,634 as the 2026 figure — the one-minute-delayed number.
2. Make the fill audit capable of failing in the sweep and profile scripts, and re-run.
   Compute `outside_exit_bar` and `signal_after_entry`; do not write them as constants.
3. Decide the concurrency policy explicitly and implement it where it can bind. Today
   nothing limits three simultaneous Calm micros, and the cap that appears to reject trades
   is a per-trade volatility filter on MNQ.
4. Re-state the in-sample record as five contributing years, not seven.
5. Correct the two record errors: the outlier-dependence read (section M5) and the p05/p95
   label (M6).
6. If a wide disaster stop ships, exercise it deliberately — it has never fired in nine
   years of data, so live will be its first execution.

Then paper-trade the sleeve shadow-only for a full quarter before it touches the account.

---

# 8. REPAIR STATUS — verified 2026-08-21, after the remediation pass

Everything in this section comes from my own re-measurement at the current working tree.
None of it comes from the remediation report. Commit unchanged: `601970b` (scratch is
untracked working-tree state).

## 8.1 Status of each finding

| Finding | Status | Evidence |
|---|---|---|
| C1 — edge lives in the first minute | **DOWNGRADED — my severity was wrong** | See 8.3 |
| C2 — sleeve cap inert | **FIXED** (`--calm-max-per-day`) | Numbers reproduce exactly; see 8.2 |
| C3 — exit-bar audit was a literal | **FIXED for exit and entry**; `signal_after_entry` still cannot fail | Mutation test, see 8.4 |
| H1 — band inverts out of sample | **STILL OPEN** — not addressed in this pass | |
| H2 — walk-forward preferred `raw`, overridden | **STILL OPEN** | |
| H3 — OOS interval spans zero | **STILL OPEN**, slightly worse under max-2 | See 8.5 |
| H4 — MNQ carries OOS | **STILL OPEN**, worse under max-2 | See 8.5 |
| H5 — five contributing years, not seven | **STILL OPEN** | |
| M3 — split variant charges one round-turn for two exits | Still one round-turn | |
| M4 / M5 / M6 — corrections to the record | Carried into the research doc | |

## 8.2 Reported numbers I could reproduce

Every figure in the remediation pass reproduces from my own repricing of the saved trade
logs against the parquet.

The same-day cap, tie-break "most negative overnight first":

| Window | base | max 2/day | max 1/day |
|---|---:|---:|---:|
| 2018-2024 | +$14,850 | +$11,576 | +$6,281 |
| 2025 | +$2,736 | +$2,400 | +$1,312 |
| 2026 | +$2,634 | +$1,600 | +$692 |
| OOS pooled | +$5,371 | +$4,000 | +$2,004 |

The extra-slippage case also checks out by hand: two extra entry ticks is $2.50 on MES and
$1.00 on MNQ and MYM, so in-sample that is 220x2.50 + 236x1.00 + 243x1.00 = $1,029, giving
$14,850 - $1,029 = $13,821. 2025: $123 gives $2,613. 2026: $91.50 gives $2,543. All match.

## 8.3 C1 — I overstated this, and the correction is right

The remediation pass says the fragility is timing rather than a small tick cost. I went
looking for the mechanism behind my own claim and could not find one.

**There is no reliable first-minute drift.** Fraction of trades where the price is higher at
the 09:31 open than at the 09:30 open: 52.0% in-sample, 56.3% in 2025, 56.5% in 2026 —
pooled 52.8%, binomial p=0.12. A coin, near enough.

**The one-minute delay cost is not distinguishable from zero in any window.** Day-clustered
bootstrap, 5,000 draws:

| Window | Delay cost | 95% interval | p |
|---|---:|---|---:|
| 2018-2024 | -$730 | [-$1,811, +$351] | 0.196 |
| 2025 | -$202 | [-$1,134, +$771] | 0.657 |
| 2026 | -$586 | [-$1,339, +$103] | 0.114 |

**And the day's move is not an opening pop — it accumulates slowly.** Share of the gross
09:30 to 15:55 point move already earned by each time:

| Window | by 09:31 | by 09:35 | by 10:00 | by 12:00 |
|---|---:|---:|---:|---:|
| 2018-2024 | 4.1% | 9.6% | 29.4% | 60.0% |
| 2025 | 6.5% | 11.8% | -11.9% | 44.0% |
| 2026 | 20.2% | 51.5% | 16.8% | 31.6% |

In-sample the sleeve has earned four percent of its move by 09:31 and sixty percent by
noon. That is a slow drift, not something that happens at the bell. 2026 is the exception,
but 2026 is 33 trading days and its own delay penalty does not reject zero.

**Why I got this wrong.** I saw a dollar delta with the same sign in three windows and read
it as a mechanism, without asking whether the delta was distinguishable from zero and
without looking at the accumulation profile — which would have shown immediately that the
edge is not an opening phenomenon. A point estimate is not a measurement.

**Revised severity: not a blocker.** It becomes a paper-trading measurement item — record
actual fill timestamps and realised slippage at 09:30 for a quarter and compare against the
09:30-open assumption. The sleeve already survives two extra entry ticks in every window, so
the cost dimension is covered. What is not covered is a systematic fill *delay* of several
minutes, which the plus-five-minute column still prices at -11.5% / -13.3% / -56.6%.

## 8.4 C3 — two gates now genuinely fail; the third still cannot

**Exit and entry bar checks are real.** I mutated the recorded exit price by 500 points and
re-ran the 2026 profile: `outside_exit_bar` went from 0/19 to **19/19**. The gate is wired
and can go red.

One residual limit worth knowing: on the time-exit path the recorded price is *read from*
the bar, so low <= open <= high holds by construction of an OHLC bar. The check can only
fire today on corrupt data — which is not nothing in this repository, given the corrupt
five-minute bars found previously. It becomes a live check the moment any exit price is
*computed* rather than read, which is exactly where it caught the NKD stop failures.

**`signal_after_entry` cannot fail.** It is written as
`1 if pd.Timestamp(entry_ts).time() < pd.Timestamp("09:30").time() else 0`, but `entry_ts`
comes from a frame already filtered to 09:30 and later (`rth = g.between_time("09:30",
"15:59")`, then the first bar at or after 09:30). The condition is false by construction;
no data can make it 1. It is a literal zero wearing an if-statement.

I proved it by widening the signal window and watching the gate not notice:

| Overnight window ends at | Shipped check | Falsifiable check |
|---|---:|---:|
| 09:30 (current, correct) | 0 / 486 | 0 / 486 |
| 09:36 (leaks 6 minutes of RTH) | **0 / 486** | 486 / 486 |
| 10:00 (leaks 30 minutes of RTH) | **0 / 486** | 486 / 486 |

The falsifiable version asks the question the gate is named after — did any bar used to
build the signal exist at or after the entry timestamp:

    "signal_after_entry": 1 if pre.index.max() >= entry_ts else 0

This passes cleanly today (0 of 486) and goes fully red the moment the overnight window
drifts into RTH. It needs `pre` in scope at the row-writing site in all three probes.

Minor, non-breaking: in the risk-filter probe the row template still writes
`"outside_entry_bar": 0` as a literal, and it happens to be overridden because `**meta`
is expanded after it. Correct today, but it reads as a hardcoded zero to the next person.

## 8.5 New — the concurrency cap changes *which* sleeve you have, not just its size

This follows from C2's fix meeting H4, and was not visible before the cap existed.

The tie-break "most negative overnight first" is not instrument-neutral. Under max-2 the
mix barely moves. Under max-1 it collapses:

| Window | Policy | MES / MNQ / MYM share of trades | MES share of P&L |
|---|---|---|---:|
| 2018-2024 | base | 31% / 34% / 35% | +32% |
| 2018-2024 | max 2 | 31% / 36% / 33% | +36% |
| 2018-2024 | **max 1** | **12% / 50% / 38%** | **+1%** |
| 2025 | base | 28% / 36% / 37% | +36% |
| 2025 | **max 1** | **2% / 51% / 47%** | +14% |
| 2026 | base | 30% / 32% / 38% | +12% |
| 2026 | **max 1** | **6% / 42% / 52%** | **-38%** |

MNQ almost always has the most negative overnight return of the three, so a max-1 rule keyed
on that value systematically drops MES. Max-1 is therefore not a smaller version of this
sleeve — it is a different, MNQ/MYM sleeve. That is a structural reason to prefer max-2, and
a better one than the P&L comparison, which is the kind of argument that selects a risk
policy by its profit.

Max-2 keeps the mix but does not improve the statistical position:

| Policy | OOS pooled | 95% interval | p | MNQ share of net |
|---|---:|---|---:|---:|
| base | +$5,371 | [-$1,479, +$12,313] | 0.129 | 71% |
| max 2 | +$4,000 | [-$2,115, +$9,993] | 0.210 | **78%** |

So H3 and H4 both get slightly worse under the honest cap, not better. That is the correct
direction — the old number was inflated by a cap that could not bind — but it should be
stated plainly rather than absorbed.

## 8.6 What to run next

The full 2018-2024 combined rerun timed out at 300 seconds in the remediation pass, and the
doc correctly labels the floor result as not refreshed. That is the right label. The rerun
is a terminal job, not a background one — the Normal/floor stage alone loads four instrument
parquets and re-fits the regime model, so expect several minutes. Run it directly and
capture to a file rather than through a tool timeout, and confirm the flag names against the
current argparse block first: the probe's own defaults are still a 12:00 exit and a -0.008
lower bound, which is not the candidate, so the flags are not optional.

## 8.7 Still open, in priority order

1. **H1** — the -1% to -0.5% bucket is +$6,930 in-sample and negative in both out-of-sample
   years. Nothing in this pass touched it, and it is the finding most likely to mean the
   band is fitted noise.
2. **H2** — the walk-forward selected the unfiltered variant in both folds with a usable
   sample. If there is a record of the three finalists being frozen before 2025 was scored,
   that changes this; otherwise the selection is out-of-sample-informed.
3. **H3 / H4** — 80 out-of-sample trading days, interval spanning zero, 71-78% from one
   instrument. This is a sample-size problem and only time fixes it.
4. **H5** — restate the in-sample record as five contributing years.
5. **`signal_after_entry`** — replace with the falsifiable form in 8.4.

---

# 9. C3 CLOSED — mutation evidence, 2026-08-21

Measured by me at the current working tree, not taken from the repair report.

## 9.1 The gate is now live in all three probes

I mutated the overnight window in-process — rewriting the source in memory so the signal
window leaks into RTH, without touching any file on disk — and re-ran each probe on MES,
2026:

| Probe | clean (window ends 09:30) | mutated to 09:36 | mutated to 10:00 |
|---|---:|---:|---:|
| `calm_neg_overnight_mae_profile.py` | 0 / 19 | **18 / 18** | **23 / 23** |
| `calm_neg_overnight_exit_sweep.py` | 0 / 19 | **18 / 18** | **23 / 23** |
| `calm_neg_overnight_risk_filter_probe.py` | 0 / 19 | **18 / 18** | **23 / 23** |

Full red under mutation, clean without it. This is the check the old form could not make —
the previous version stayed at 0 in every one of these mutations. C3 is closed.

Both selection routines now consume the field: `select_candidates` in the sweep and in the
risk-filter probe require all three audit counters to be zero before a variant can be kept.

## 9.2 Non-regression — the refactor did not move a single number

Fresh run of the fixed sweep against the pre-fix saved log, 2026 window:

| | Trades | Net | Same day+instrument set | Max per-trade difference |
|---|---:|---:|---|---:|
| fresh code | 63 | $2,634.38 | — | — |
| saved log (pre-fix) | 63 | $2,634.38 | yes | **0.0000000000** |

So the audit-gate work is behaviour-preserving, and nothing measured earlier in this
document needs revising.

## 9.3 Two residuals, both narrow

**The saved trade logs are stale, so no artifact on disk yet carries a real audit value.**
The probes were fixed at 02:19 today; the saved logs were written between 20:01 and 22:42
yesterday. The in-sample log's header is still
`...,pnl,outside_exit_bar,overnight_ret` — the two new columns do not exist in it, and its
`outside_exit_bar` column is the old hardcoded literal. Every gate is live *for a fresh
run*; none of the currently saved files has been through one.

**`calm_neg_overnight_wfo_stability.py:51` was not updated.** Its `eligible()` test still
checks only `outside_exit_bar`, and it reads the stale in-sample log — so the walk-forward
eligibility gate is still reading a constant, exactly the condition C3 was raised about.

The safe order is to fix the gate first and regenerate second: if the two new columns are
added to `eligible()` while the log is still stale, the script raises a missing-column
error, which is a loud failure. Regenerating first and updating the gate second leaves a
window where the walk-forward silently skips two of the three checks.

## 9.4 Where the record stands

Fill and timing mechanics: **verified, with gates that can now fail.**
Execution latency (C1): **downgraded to a paper-trading measurement item**, with the reason
recorded in section 8.3.
Concurrency (C2): **fixed**, and the max-1 variant is understood to be a different sleeve
rather than a smaller one.

Still open and untouched: H1 (band boundaries invert out of sample), H2 (the walk-forward
preferred the unfiltered variant in both folds with a usable sample), H3 and H4 (80
out-of-sample trading days, interval spanning zero, 71-78% of net from one instrument), H5
(five contributing years, not seven). These are not code defects and no code change will
close them.

---

# 10. ARTIFACTS REFRESHED — verified 2026-08-21

Measured by me at the current working tree.

## 10.1 The repair holds

**Fail-loud works.** I built a stale-shaped input by stripping the two new columns from the
regenerated log and ran the walk-forward against it: exit code 1,
`ValueError: missing audit columns in WFO input: ['outside_entry_bar', 'signal_after_entry']`.

**The regenerated artifacts changed no number.** All three windows, all three finalists,
against the figures recorded before any of the gate work began:

| Window | Variant | Trades | Net | Match |
|---|---|---:|---:|---|
| 2018-2024 | raw | 1,036 | +$15,205 | yes |
| 2018-2024 | mod001 | 699 | +$14,850 | yes |
| 2018-2024 | mod002 | 461 | +$14,383 | yes |
| 2025 | raw / mod001 | 132 / 87 | +$5,285 / +$2,736 | yes |
| 2026 | raw / mod001 | 76 / 63 | +$2,440 / +$2,634 | yes |

Audit counters on the fresh logs: `outside_exit_bar=0`, `outside_entry_bar=0`,
`signal_after_entry=0` in every window. Row arithmetic checks: 1,036 + 699 + 461 = 2,196,
the walk-forward's loaded row count.

`mod002_010_x1555` is still absent from the regenerated out-of-sample logs, so the
provenance point in H2 is unchanged — its 2025 and 2026 figures still come from a separate
pass, not from this pipeline.

## 10.2 The refreshed walk-forward sharpens H2 rather than settling it

With the gates live and the artifacts fresh, the fold selections are unchanged. The
held-out years now say something more pointed than "the walk-forward preferred `raw`".

Each variant held fixed across the three test years:

| Variant | 2022 | 2023 | 2024 | Sum | Trades | Per trade |
|---|---:|---:|---:|---:|---:|---:|
| raw | +$194 | **+$5,563** | +$687 | **+$6,444** | 372 | $17.32 |
| **mod001 (promoted)** | +$171 | +$3,766 | +$1,776 | **+$5,713** | 260 | $21.97 |
| mod002 | **+$306** | +$4,112 | **+$1,982** | +$6,401 | 167 | **$38.33** |

Rank by test year: 2022 mod002 > raw > **mod001**; 2023 raw > mod002 > **mod001**;
2024 mod002 > **mod001** > raw.

**The promoted candidate is last in two of the three held-out years and first in none.**
Summed across all held-out data it is the lowest of the three on dollars, the middle on
dollars-per-trade, and it does not win the drawdown comparison either (in-sample maximum
drawdown: mod002 $1,739 < mod001 $1,881 < raw $2,216).

And following the walk-forward is worth nothing over the simplest variant:

| Policy | Held-out net | Trades |
|---|---:|---:|
| follow the walk-forward's per-fold pick | +$6,421 | 368 |
| always trade `raw` | +$6,444 | 372 |
| always trade `mod001` | +$5,713 | 260 |
| always trade `mod002` | +$6,401 | 167 |

The selection machinery reproduces the do-nothing variant to within $23.

**What this does and does not say.** It does not say switch to `mod002` — ranking variants
on the same three held-out years that just produced this table is the identical mistake one
level deeper, and `mod002`'s out-of-sample figures were never generated by this pipeline.
What it says is that under all three natural criteria — dollars, dollars per trade,
drawdown — the held-out evidence does not pick `mod001`. With 260 to 372 trades spread over
three years, the three variants are not separable, and the candidate was promoted on a
tiebreak the held-out data does not reproduce.

## 10.3 One robustness gate is still leaning on a year that barely exists

Every fold's train window reports `posY=4`, clearing the `min_years=3` requirement. But one
of those four years is 2022, which carries 1 to 6 trades depending on the variant. The
walk-forward's own robustness gate is therefore partly satisfied by a year in which the
strategy did not trade — the same issue as H5, now visible inside the selection logic.
The 2022 test fold has the same problem: 2 trades for the candidate, 1 for `mod002`.

## 10.4 Status

| Finding | Status |
|---|---|
| C1 | Downgraded to a paper-trading measurement item (section 8.3) |
| C2 | Fixed; max-1 understood as a different sleeve, not a smaller one |
| C3 | **Closed** — gates mutation-tested live, artifacts regenerated, walk-forward gate fails loud |
| H1 | Open — band boundaries invert out of sample |
| H2 | Open, and **sharper**: the candidate is first in none of the three held-out years |
| H3 / H4 | Open — 80 out-of-sample days, interval spanning zero, 71-78% from one instrument |
| H5 | Open, and now visible inside the walk-forward's own gate (section 10.3) |

Every code-level finding is closed. Everything still open is a question about evidence, and
no code change will close any of it.
