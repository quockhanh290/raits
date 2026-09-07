# Audit — Calm deploy-pilot candidate `calm_openloc_lower_third_long_e1000_x1555`

Date: 2026-08-21 (machine clock: Calgary, MDT). Commit: `601970b`.
Contract: read-only. No production code touched, nothing committed.

Every number below is my own measurement against local parquet and the saved logs.

---

## Verdict, first

**REJECT.**

The blocker is not the signal, the fills, or the costs. It is the Calm gate.

The regime label for day D is produced by feeding the HMM SPY closes up to and including
day D, and reading the last state. Its two features are day D's log-return and the 5-day
realised volatility ending at day D. Both require SPY's **16:00 close on day D**. The
candidate enters at **10:00 on day D**. The label the backtest uses is therefore not
knowable at entry — it is a six-hour look-ahead.

Replacing it with the freshest label a live system could actually hold at 10:00 — the
previous session's label — removes the entire result:

| Window | As reported (same-day label) | Causal (previous session's label) | Change |
|---|---:|---:|---:|
| 2018-2024 | +$9,049, PF 1.41 | **-$769, PF 0.98** | -$9,818 |
| 2025 | +$4,925, PF 3.81 | +$1,935, PF 1.48 | -$2,990 |
| 2026 to 08-19 | +$1,485, PF 1.44 | **-$2,514, PF 0.60** | -$4,000 |
| **2025+2026 pooled** | +$6,410 | **-$579** | -$6,989 |

And the signal on its own, with no regime gate at all, is negative in-sample: **-$10,675
over 1,698 trades, PF 0.91, 50.7% winners.** Every causal way of slicing the in-sample
window is negative or zero. The only positive slice is the one that requires knowing how
the day ends.

---

## 1. What reproduces, and what is genuinely clean

The reported numbers reproduce exactly from the saved logs: 666 trades / +$9,049 / PF 1.41 /
MaxDD $1,706 in-sample; 73 / +$5,237 / PF 4.64 in 2025; 48 / +$1,485 / PF 1.44 in 2026;
121 / +$6,723 / PF 2.39 pooled. Audit counters 0/0/0 in every window.

**The price-side timing is correct.** Signal timestamp is the 09:30 bar in 666 of 666
trades, entry is the 10:00 bar in 666 of 666, exit is the 15:55 bar in 666 of 666, and the
entry timestamp is strictly later than the signal timestamp in every single trade. There is
a real 30-minute gap between the information and the fill.

**The signal uses only what is available at 09:30.** `open_loc` is built from `p0930` — the
*open* of the 09:30 bar — divided into the prior day's RTH range. The prior range comes from
a one-row shift of a frame sorted by trading day, so it is the previous session's high and
low, never the same day's. No 10:00 bar close, high, or low touches either the signal or the
entry price; the entry price is that bar's open.

**Band membership is exact**: maximum `open_loc` is 0.3333 in-sample, 0.3271 in 2025, 0.3213
in 2026, with zero violations of the one-third rule.

**The evening-session rollover is handled.** Bars at or after 18:00 are assigned to the next
trading day before the RTH slice is taken, so no overnight bar leaks into an RTH range.

**One suspected defect that is not a defect.** I checked whether the unused SPY 50-day
average silently drops days — the generation loop skips a day when it is missing, even for
variants that never reference it. It has zero missing values anywhere in the windows used,
first valid date 2017-03-16. No days are lost.

---

## 2. The blocker, in detail

### 2.1 What the label consumes

`label_regimes` fits the HMM once, then labels each day by calling `predict_current` on all
SPY closes up to that day and taking the **last** state. `build_feature_matrix` builds two
columns: the daily log-return, and the 5-day rolling realised volatility. The last row of
that matrix — the row whose state is returned — is day D's own return and a vol window
ending on day D.

There is no way to compute that at 10:00. This is the same defect the Stress sleeve audit
already found for its 10:20 entry and fixed by moving to previous-session labels. The fix
was never carried across to Calm.

### 2.2 Only 14% of days change, and they carry 100% of the result

In-sample the two labellings agree on 736 of 796 Calm days — a Jaccard overlap of 0.86.
Sixty days enter under the same-day label, sixty leave. The decomposition reconciles to the
dollar:

| Day set | Trades | Net | Average | PF |
|---|---:|---:|---:|---:|
| Calm under both labellings | 631 | +$9,044 | +$14.33 | 1.44 |
| Calm only under the same-day label | 35 | +$5 | +$0.15 | 1.00 |
| **= as reported** | **666** | **+$9,049** | | **1.41** |
| Calm only under the causal label | 79 | **-$9,813** | **-$124.22** | 0.19 |
| **= causal total** | **710** | **-$769** | | **0.98** |

### 2.3 The mechanism is not fake winners — it is filtered losers

The days added by the look-ahead are worth $5. Nothing. The damage is entirely on the other
side: the 79 trades on days the same-day label **excludes**.

What those days are:

| Day set | SPY return that day, mean | median | share up |
|---|---:|---:|---:|
| Calm under the same-day label | +0.094% | +0.094% | 59.0% |
| Calm under the causal label | +0.042% | +0.073% | 56.8% |
| Days the same-day label pulls IN | +0.136% | +0.154% | 66.7% |
| **Days the same-day label pushes OUT** | **-0.559%** | **-1.227%** | **36.7%** |
| All days in the window | +0.052% | +0.076% | 55.0% |

The HMM's Calm state is partly defined by day D's own return, so "Calm on D" is close to
"SPY did not fall on D". Those excluded days have a median SPY return of **-1.23%**. A live
system holding the previous session's label would have been long three index futures from
10:00 to 15:55 on 79 of them, at an average of -$124 per trade.

**The reported edge is precisely the value of knowing, at 10:00, that the day will not be a
bad day.** That is worth $9,813 in-sample, which is the whole $9,049.

### 2.4 The signal has no edge of its own

Applying `open_loc <= 1/3`, LONG, 10:00 to 15:55, under each possible day gate:

| Gate | 2018-2024 | 2025 | 2026 |
|---|---|---|---|
| none — every day | **-$10,675** / 1,698 / PF 0.91 | +$15,079 / 227 / PF 1.87 | +$9 / 144 / PF 1.00 |
| same-day Calm (as reported) | +$9,049 / 666 / PF 1.41 | +$4,925 / 76 / PF 3.81 | +$1,485 / 48 / PF 1.44 |
| causal Calm | -$769 / 710 / PF 0.98 | +$1,935 / 84 / PF 1.48 | -$2,514 / 53 / PF 0.60 |
| causal Normal | -$11,289 / 857 / PF 0.84 | +$8,188 / 120 / PF 1.91 | +$839 / 86 / PF 1.09 |
| causal not-Stress | -$12,058 / 1,567 / PF 0.88 | +$10,123 / 204 / PF 1.78 | -$1,676 / 139 / PF 0.89 |

Two things follow.

The ungated signal loses money in-sample over 1,698 trades at a 50.7% win rate. It is not a
weak edge; it is no edge.

And 2025's strength is a **year effect, not a signal effect**. The ungated version earns
+$15,079 on 227 trades in 2025 — three times the candidate's +$4,925 on 76. If the filter
were selecting good days it would beat the unfiltered version, not trail it by two-thirds.
Buying the 10:00 bar and selling at 15:55 simply worked in 2025 regardless of open location
or regime.

---

## 3. This is not specific to this candidate

The same gate sits under the Calm sleeve certified earlier this week. I re-ran it with
causal labels:

`on_neg_fade_mod001_010_x1555`:

| Window | As reported | Causal | Change |
|---|---:|---:|---:|
| 2018-2024 | +$14,850, PF 1.60 | **-$375, PF 0.99** | -$15,226 |
| 2025 | +$2,736, PF 1.54 | +$1,146, PF 1.19 | -$1,590 |
| 2026 | +$2,634, PF 1.58 | **-$3,705, PF 0.59** | -$6,340 |
| **2025+2026 pooled** | +$5,371 | **-$2,559** | -$7,930 |

**My audit of that candidate on 2026-08-21 did not test label causality, and its verdict —
"research-confirmed but not production-ready" — was too generous.** Under labels a live
system could hold, that candidate has no in-sample edge either. I audited the overnight
window, the trading-day rollover, the band, the SPY short filter and the bar-level fills,
and confirmed each of them; I never asked what the regime label itself consumes. The finding
was sitting in the same research document, in the Stress section, where lag-1 labels had
already been adopted as the causal comparison. I did not carry it across.

Both Calm sleeves need re-certifying under causal labels before any of their numbers are
used again.

---

## 4. Why the fold protocol cannot rescue this

I did not re-run the 300/150 and 300/100 sample-count folds, and re-running them would not
change the verdict. Both the train and the test halves of every fold are drawn from the same
same-day-labelled Calm day set. A cross-validation scheme cannot detect a non-causal gate:
it inherits the gate on both sides of every split. The reported held-out aggregates
(+$6,661 over 365 trades, +$6,872 over 406) are measuring how stable the look-ahead is, not
whether the strategy is tradeable.

The calendar-year fold caveat in the brief — 2022 has only 6 Calm days — is correct and I
reproduce it: the candidate has 5 trades in 2022 in-sample.

---

## 5. Findings that survive the rejection, for whoever rebuilds this

**The prior RTH range is sometimes stale.** Days are dropped when the RTH session has fewer
than 160 one-minute bars, and the "previous day" is then the previous *surviving* row. On 62
of 1,743 in-sample days the prior row is more than one session back (maximum five calendar
days), affecting about 5% of signal days. Not a look-ahead — the range is still fully in the
past — but the feature is not always the immediately preceding session.

**The 2025 Calm universe in the artifacts is a strict subset of the HMM's.** The generation
script prefers a day-list CSV when one exists, and that CSV covers 92 of the 113 HMM Calm
days in 2025 — 21 missing, none extra. The day set was inherited from an older excavation
script's own data filters. This is why the saved 2025 figure is 73 trades / +$5,237 while a
direct HMM-labelled run gives 76 / +$4,925. Small, but the artifacts are not measuring the
universe the spec describes.

**`signal_after_entry` still cannot fail in this probe.** It is `1 if signal_ts > entry_ts`,
where the signal timestamp is the first bar at or after 09:30 and the entry timestamp is the
first bar at or after 10:00 on the same sorted frame. The second is always at least the
first. The property it asserts is true — I verified it independently — but the check itself
is a constant, the same pattern corrected in the other Calm probes. Note also that these
three counters would not have caught the actual blocker: they audit bars and timestamps, and
the look-ahead is in the regime label, which they never touch.

**The entry and exit bar checks are near-tautological here.** Both prices are read straight
from the bar being checked, so `low <= open <= high` holds by construction. They can only
fire on corrupt data. That is worth something in this repository, but it is not evidence of
fill feasibility for a computed price such as a stop.

---

## 6. What I did not measure, and why

- **Stop-variant fill feasibility (task 3).** Not measured. The 2.0x ATR stop reportedly
  never fires and the 1.5x fires twice in-sample; with the base result at -$769 under causal
  labels, stop realism cannot change the outcome.
- **Slippage at 3, 4 and 6 ticks (task 6).** Not pursued. The reported ladder is on
  non-causal numbers, and lowering costs does not turn -$769 positive.
- **Monthly contribution and instrument-removal (task 6).** Not pursued for the same reason.
  I did measure the instrument split: in-sample MES +$2,220 / MNQ +$4,706 / MYM +$2,124, and
  in 2026 MES +$186 / MNQ +$1,508 / MYM -$210. All of these are same-day-label numbers.
- **Sample-count folds (task 5).** Not re-run — see section 4 for the structural reason.

---

## 7. The specific blocker, stated for the record

To make any Calm-gated futures sleeve tradeable, the regime gate must be computable at the
entry timestamp. Three doors are open, in increasing order of work:

1. **Previous-session labels.** Legitimate and already adopted for the Stress sleeve. Under
   it, neither Calm candidate currently has an in-sample edge — so this is not a relabelling
   exercise, it is a return to signal research.
2. **A genuinely intraday Calm detector** built from information available by 09:30 or
   10:00: overnight futures range, pre-open volume, prior-session close-to-open behaviour.
   This is a real research direction and would need its own certification.
3. **Drop the regime gate** and find a signal that stands without one. The measurement in
   section 2.4 says `open_loc <= 1/3` is not that signal: -$10,675 over 1,698 in-sample
   trades.

Until one of those exists, no Calm sleeve number in the research record should be quoted as
a tradeable expectation, including the ones I previously certified as clean on their
mechanics. Their mechanics *are* clean. The gate above them is not.
