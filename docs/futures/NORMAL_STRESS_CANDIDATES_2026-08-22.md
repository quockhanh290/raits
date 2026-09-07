# Normal / Stress Candidate Snapshot - 2026-08-22

Scratch/research summary. Production code was not modified by this pass.

## Current Portfolio Candidate

This is the strongest measured portfolio configuration from the latest Normal/Stress/NKD probes:

```text
Account: $50,000

Normal-R4:
  Instruments: MES, MNQ, MYM, M2K
  Quantity: 1 micro per accepted trade
  Cluster: roska4_swing
  Cap: 5.0% gross / 4.4% net

Stress-MNQ:
  Instrument: MNQ only
  Quantity: 7 MNQ micros
  Cluster: roska4_stress
  Cap: 10.0% gross-only

NKD/MNKD:
  Instrument: MNKD
  Quantity: 1 micro
  Cluster: global_nkd
  Cap: 6.0% gross / 6.0% net

Account breaker:
  Hard drawdown halt: 15% from peak equity
  Daily loss halt: 4%
```

Verdict: this is a **portfolio research / paper candidate**, not production deploy yet. The Stress
component still has very sparse 2025/2026 evidence and needs live switch/broker audit.

## Normal-R4 Strategy

Scope:

- Regime: `Normal`
- Instruments: `MES`, `MNQ`, `MYM`, `M2K`
- Quantity: 1 micro
- NKD/MNKD is not part of the R4 cluster.

Signal:

- Base: Ro-4 swing trend-follow.
- EMA: 50.
- Stop: 2x daily ATR logic in signal, risk cap replay uses 2.5x ATR risk sizing convention.
- Stop is fixed and armed at 14:05 next session.
- Max hold: 5 days.
- Short filter: allow SHORT only when SPY D-1 close is below SMA50.
- Slippage/cost: 2 ticks per side.

R4 filter:

- Rule name: `range_p90__vol_le_2`.
- Applies only to R4, not NKD.
- Prior-day futures RTH range must be <= floor-derived R4 p90.
- Entry-bar relative volume must be <= 2.0x median volume of prior 20 sessions at the same time slot.
- Entry-bar volume is live-feasible because the engine enters at the close of the completed resume bar.

Risk:

```text
Normal-R4 cluster cap:
  gross <= 5.0% of $50k = $2,500
  net   <= 4.4% of $50k = $2,200

Normal per-trade risk:
  daily_ATR * 2.5 * point_value * 1 contract
```

## Stress-MNQ Strategy

This candidate does **not** use the same-day daily `Stress` regime label. It is an intraday stress
detector designed to avoid the earlier lag-0 regime lookahead problem.

Variant:

- Name: `mnq_only_g3_q7`
- Instrument: `MNQ`
- Direction: SHORT
- Quantity: 7 MNQ micros
- Setup time: 10:30 ET
- Setup known time: 10:35 ET
- Entry window: after 10:35 through 12:30
- Exit: 15:55
- RR: 1.5R

Detector:

- By 10:30, all 4 R4 instruments are below both:
  - current day open;
  - VWAP computed through the setup window.
- At least 3 of 4 R4 instruments gap down versus prior RTH close.
- Average gap must satisfy the candidate's gap-continuation condition.

Entry:

- Short MNQ on break of the 09:30-10:30 low after the signal is known.

Stop and target:

```text
stop   = setup_high * 1.001
dist   = stop - entry
target = entry - 1.5 * dist
```

Stress risk cap:

```text
Stress cap:
  gross <= 10.0% of $50k = $5,000

Stress per-trade risk:
  abs(stop - entry) * MNQ_point_value * qty
  abs(stop - entry) * $2 * 7

Max stop distance under 10% cap:
  $5,000 / ($2 * 7) = 357.14 MNQ points
```

Switch policy:

1. If Stress signal appears, first simulate closing any existing same-symbol Normal `MNQ` position.
2. If Stress is still admissible after that simulated close, close Normal `MNQ` at Stress entry open.
3. Enter Stress short `MNQ` 7x.
4. While Stress `MNQ` remains open, suppress new Normal `MNQ` entries.
5. If Stress is rejected by cap/breaker, leave existing Normal untouched.

Operational reason: avoid simultaneous same-symbol Normal long/Stress short exposure and avoid
broker/netting mismatch.

## NKD/MNKD Strategy

NKD/MNKD is included only as a separate portfolio diversifier, not as part of the Stress sleeve.

Scope:

- Instrument: `MNKD`
- Quantity: 1 micro
- Cluster: `global_nkd`
- Cap: 6.0% gross / 6.0% net
- Signal source: existing NKD swing trade artifact in `normal_promotion_trades_*_20260821.json`.

Risk:

```text
NKD cap:
  gross <= 6.0% of $50k = $3,000
  net   <= 6.0% of $50k = $3,000

NKD per-trade risk:
  daily_ATR * 2.5 * point_value * 1 contract
```

NKD quantity sweep result: do **not** increase to qty 2 yet. Qty 2 improves some net rows but worsens
floor/2025 MaxDD and is cap-sensitive in 2026.

## Measured Portfolio Results

Policy measured:

```text
Normal-R4: 5.0% gross / 4.4% net, qty 1
Stress-MNQ: 10.0% gross, qty 7
NKD/MNKD: 6.0% gross / 6.0% net, qty 1
```

| Window | Book | Trades attempted | R4 taken/rej | Stress taken/rej | NKD taken/rej | Net | Return | PF | Sharpe | Calmar | MaxDD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| floor 2018-2024 | R4 only | 752 | 546 / 206 | 0 / 0 | 0 / 0 | +$29,046 | 58.1% | 1.49 | 2.25 | 0.68 | $6,209 |
| floor 2018-2024 | R4 + Stress | 802 | 551 / 192 | 49 / 1 | 0 / 0 | +$52,139 | 104.3% | 1.75 | 2.97 | 1.15 | $6,646 |
| floor 2018-2024 | R4 + NKD | 980 | 546 / 206 | 0 / 0 | 228 / 0 | +$32,944 | 65.9% | 1.40 | 1.84 | 0.79 | $6,078 |
| floor 2018-2024 | R4 + Stress + NKD | 1030 | 551 / 192 | 49 / 1 | 228 / 0 | +$56,037 | 112.1% | 1.61 | 2.45 | 1.67 | $4,893 |
| 2025 | R4 only | 105 | 55 / 50 | 0 / 0 | 0 / 0 | +$5,395 | 10.8% | 1.58 | 1.94 | 1.56 | $3,768 |
| 2025 | R4 + Stress | 108 | 55 / 50 | 3 / 0 | 0 / 0 | +$10,167 | 20.3% | 2.37 | 3.49 | 3.12 | $3,540 |
| 2025 | R4 + NKD | 136 | 55 / 50 | 0 / 0 | 31 / 0 | +$7,598 | 15.2% | 1.53 | 2.01 | 1.45 | $5,679 |
| 2025 | R4 + Stress + NKD | 139 | 55 / 50 | 3 / 0 | 31 / 0 | +$12,370 | 24.7% | 1.99 | 3.23 | 2.80 | $4,792 |
| 2026 sanity | R4 only | 81 | 46 / 35 | 0 / 0 | 0 / 0 | +$1,059 | 2.1% | 1.16 | 0.87 | 0.47 | $4,075 |
| 2026 sanity | R4 + Stress | 85 | 46 / 35 | 3 / 1 | 0 / 0 | +$1,890 | 3.8% | 1.24 | 1.21 | 0.93 | $3,656 |
| 2026 sanity | R4 + NKD | 107 | 46 / 35 | 0 / 0 | 24 / 2 | +$7,066 | 14.1% | 1.58 | 2.88 | 2.43 | $5,253 |
| 2026 sanity | R4 + Stress + NKD | 111 | 46 / 35 | 3 / 1 | 24 / 2 | +$7,898 | 15.8% | 1.59 | 2.89 | 2.93 | $4,877 |

Interpretation:

- `R4 + Stress + NKD` is the best measured portfolio row on floor Calmar and 2026 sanity.
- `R4 + Stress` is cleaner as a Stress-specific test and has stronger 2025 MaxDD than adding NKD.
- NKD helps floor combined MaxDD materially but worsens 2025 MaxDD relative to `R4 + Stress`.

## Cap Studies

### Stress Cap

For `mnq_only_g3_q7`, cap below 7.5% rejects too many OOS Stress legs.

| Window | Stress cap | Stress taken/rej | Net | PF | Sharpe | Calmar | MaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|
| floor | 5.0% | 32 / 18 | +$46,189 | 1.74 | 2.99 | 1.31 | $5,151 |
| floor | 7.5% | 47 / 3 | +$49,724 | 1.72 | 2.85 | 1.09 | $6,646 |
| floor | 10.0% | 49 / 1 | +$52,139 | 1.75 | 2.97 | 1.15 | $6,646 |
| 2025 | 7.5% | 2 / 1 | +$10,329 | 2.42 | 3.59 | 3.17 | $3,540 |
| 2025 | 10.0% | 3 / 0 | +$10,167 | 2.37 | 3.49 | 3.12 | $3,540 |
| 2026 sanity | 7.5% | 1 / 3 | +$2,688 | 1.40 | 1.97 | 1.33 | $3,656 |
| 2026 sanity | 10.0% | 3 / 1 | +$1,890 | 1.24 | 1.21 | 0.93 | $3,656 |

Decision: if this Stress variant is carried forward, use **Stress cap 10%** for the paper/research
candidate. Treat the higher cap as an explicit risk tradeoff.

### Single-Cap Test

Rejected. A single cap loosens Normal at the same time as Stress, so results become inseparable
from a Normal cap expansion and MaxDD increases materially.

| Window | Policy | Normal cap | Stress cap | Net | PF | Sharpe | Calmar | MaxDD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| floor | split current | 5.0% / 4.4% | 10.0% | +$52,139 | 1.75 | 2.97 | 1.15 | $6,646 |
| floor | single 10 | 10.0% / 10.0% | 10.0% | +$53,098 | 1.55 | 2.38 | 0.72 | $10,729 |
| 2025 | split current | 5.0% / 4.4% | 10.0% | +$10,167 | 2.37 | 3.49 | 3.12 | $3,540 |
| 2025 | single 10 | 10.0% / 10.0% | 10.0% | +$11,746 | 1.74 | 2.90 | 1.93 | $6,612 |
| 2026 sanity | split current | 5.0% / 4.4% | 10.0% | +$1,890 | 1.24 | 1.21 | 0.93 | $3,656 |
| 2026 sanity | single 10 | 10.0% / 10.0% | 10.0% | +$4,293 | 1.33 | 1.60 | 0.96 | $8,090 |

Decision: keep split caps.

### NKD Quantity / Cap Sweep

Fixed book: Normal-R4 qty 1, Stress-MNQ qty 7 cap 10%. Sweep only NKD.

| Window | NKD config | Net | PF | Sharpe | Calmar | MaxDD | NKD taken/rej |
|---|---|---:|---:|---:|---:|---:|---:|
| floor | off | +$52,139 | 1.75 | 2.97 | 1.15 | $6,646 | 0 / 0 |
| floor | q1 cap6 | +$56,037 | 1.61 | 2.45 | 1.67 | $4,893 | 228 / 0 |
| floor | q2 cap6 | +$62,061 | 1.54 | 2.38 | 1.25 | $7,260 | 225 / 3 |
| 2025 | off | +$10,167 | 2.37 | 3.49 | 3.12 | $3,540 | 0 / 0 |
| 2025 | q1 cap6 | +$12,370 | 1.99 | 3.23 | 2.80 | $4,792 | 31 / 0 |
| 2025 | q2 cap6 | +$13,381 | 1.76 | 2.95 | 2.40 | $6,044 | 28 / 3 |
| 2026 sanity | off | +$1,890 | 1.24 | 1.21 | 0.93 | $3,656 | 0 / 0 |
| 2026 sanity | q1 cap6 | +$7,898 | 1.59 | 2.89 | 2.93 | $4,877 | 24 / 2 |
| 2026 sanity | q2 cap12 | +$15,258 | 1.83 | 3.54 | 4.64 | $5,952 | 23 / 2 |

Decision: keep NKD at **qty 1 / cap 6%**. Do not promote qty 2 yet.

### Calm-NKD Switch Test

Scratch artifacts:

- `scratch/calm_nkd_switch_vs_current_20260822.py`
- `scratch/calm_nkd_switch_vs_current_20260822_report.md`
- `scratch/calm_nkd_switch_vs_current_20260822.json`

Question: instead of adding Calm-NKD on top of current NKD blindly, test a switch mechanism:
when Calm-NKD is admitted, close any open current MNKD position at the Calm-NKD entry price,
enter Calm-NKD, and suppress current NKD entries while Calm-NKD remains open.

Base book is fixed:

```text
Normal-R4 filtered qty 1
Stress-MNQ mnq_only_g3_q7 qty 7, cap 10%
NKD cap 6%
Calm-NKD variant: nkd_swing_d1calm_as_normal_ema5_mult2.5
```

Rows measured:

- `current_nkd`: current portfolio candidate.
- `calm_nkd_replacement`: use Calm-NKD instead of current NKD.
- `current_nkd_plus_calm_switch`: keep current NKD, but Calm-NKD overrides current NKD on overlap.

| Window | Mode | Current NKD trades | Calm-NKD trades | NKD taken/rej | Calm closed current | Suppressed current | Net | PF | Sharpe | Calmar | MaxDD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| floor | current_nkd | 228 | 0 | 228 / 0 | 0 | 0 | +$56,037 | 1.61 | 2.45 | 1.67 | $4,893 |
| floor | calm_nkd_replacement | 0 | 550 | 550 / 0 | 0 | 0 | +$59,295 | 1.73 | 2.07 | 1.27 | $6,691 |
| floor | current_nkd_plus_calm_switch | 228 | 550 | 758 / 0 | 45 | 20 | +$64,094 | 1.64 | 1.93 | 1.74 | $5,274 |
| 2025 | current_nkd | 31 | 0 | 31 / 0 | 0 | 0 | +$12,370 | 1.99 | 3.23 | 2.80 | $4,792 |
| 2025 | calm_nkd_replacement | 0 | 90 | 90 / 0 | 0 | 0 | +$12,644 | 2.25 | 2.44 | 3.57 | $3,611 |
| 2025 | current_nkd_plus_calm_switch | 31 | 90 | 117 / 0 | 7 | 4 | +$16,166 | 2.23 | 2.70 | 4.07 | $4,057 |
| 2026 sanity | current_nkd | 26 | 0 | 24 / 2 | 0 | 0 | +$7,898 | 1.59 | 2.89 | 2.93 | $4,877 |
| 2026 sanity | calm_nkd_replacement | 0 | 44 | 43 / 1 | 0 | 0 | +$3,573 | 1.33 | 1.39 | 1.60 | $3,656 |
| 2026 sanity | current_nkd_plus_calm_switch | 26 | 44 | 62 / 3 | 5 | 5 | +$8,926 | 1.65 | 2.58 | 3.37 | $4,342 |

Interpretation:

- Pure Calm-NKD replacement is not better overall: it improves 2025 MaxDD and Calmar, but it gives
  up too much 2026 net versus current NKD.
- The switch/add mode improves net in all windows and improves 2025/2026 Calmar versus current NKD,
  but it is no longer a simple replacement. It adds many non-overlapping Calm-NKD trades and uses
  switch only on overlaps.
- Floor MaxDD worsens versus current NKD (`$4,893 -> $5,274`) while net improves.

Decision: `current_nkd_plus_calm_switch` is worth carrying as a **paper/research challenger**, but
do not replace the current NKD module yet. If promoted later, production must implement MNKD
same-symbol switch semantics exactly and log every forced close/suppressed current-NKD entry.

### Calm A Combined Add-On Test

Scratch artifacts:

- `scratch/calm_a_combined_replay_20260822.py`
- `scratch/calm_a_combined_replay_20260822_report.md`
- `scratch/calm_a_combined_replay_20260822.json`

Candidate A:

```text
Calm PCLoc bottom-down not-deep-gap
Gate: D-1 Calm causal
Instruments: MES/MNQ
Direction: LONG
Entry: 10:00 ET open
Exit: 15:55 ET open
No stop/target
```

Base for this test is the strongest current research book:

```text
Normal-R4 filtered qty 1
Stress-MNQ mnq_only_g3_q7 qty 7, cap 10%
Current NKD + Calm-NKD switch challenger
```

Because Candidate A has no explicit stop, the Calm cap uses the same ATR risk proxy as the
portfolio replay (`daily_ATR * 2.5 * point_value`). This is an admission/risk-budget proxy, not a
true stop-loss.

Main rows:

| Window | Policy | Calm cap | Cost ticks/side | Calm attempted | Calm taken/rej | Calm suppressed | Net | PF | Sharpe | Calmar | MaxDD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| floor | base before Calm A | -- | -- | 0 | 0 / 0 | 0 | +$64,094 | 1.64 | 1.93 | 1.74 | $5,274 |
| floor | skip same-symbol | 1.5% | 2 | 349 | 183 / 159 | 7 | +$66,886 | 1.64 | 1.94 | 1.94 | $4,923 |
| floor | skip same-symbol | 2.5% | 2 | 349 | 255 / 87 | 7 | +$67,586 | 1.62 | 1.93 | 1.96 | $4,923 |
| floor | skip same-symbol | 5.0% | 2 | 349 | 335 / 7 | 7 | +$72,732 | 1.65 | 2.06 | 2.11 | $4,923 |
| 2025 | base before Calm A | -- | -- | 0 | 0 / 0 | 0 | +$16,166 | 2.23 | 2.70 | 4.07 | $4,057 |
| 2025 | skip same-symbol | 1.5% | 2 | 44 | 11 / 31 | 2 | +$16,483 | 2.25 | 2.73 | 4.15 | $4,057 |
| 2025 | skip same-symbol | 2.5% | 2 | 44 | 25 / 17 | 2 | +$16,889 | 2.26 | 2.72 | 4.29 | $4,014 |
| 2025 | skip same-symbol | 5.0% | 2 | 44 | 38 / 4 | 2 | +$17,881 | 2.32 | 2.85 | 4.63 | $3,943 |
| 2026 sanity | base before Calm A | -- | -- | 0 | 0 / 0 | 0 | +$8,926 | 1.65 | 2.58 | 3.37 | $4,342 |
| 2026 sanity | skip same-symbol | 1.5% | 2 | 28 | 0 / 27 | 1 | +$8,926 | 1.65 | 2.58 | 3.37 | $4,342 |
| 2026 sanity | skip same-symbol | 2.5% | 2 | 28 | 12 / 15 | 1 | +$8,881 | 1.63 | 2.45 | 3.26 | $4,342 |
| 2026 sanity | skip same-symbol | 5.0% | 2 | 28 | 15 / 12 | 1 | +$10,132 | 1.72 | 2.77 | 3.72 | $4,342 |

Cost sensitivity at Calm cap 2.5%, skip same-symbol:

| Window | 2 ticks | 3 ticks | 4 ticks | 6 ticks |
|---|---:|---:|---:|---:|
| floor net | +$67,586 | +$67,164 | +$66,743 | +$65,900 |
| 2025 net | +$16,889 | +$16,831 | +$16,773 | +$16,657 |
| 2026 sanity net | +$8,881 | +$8,851 | +$8,821 | +$8,761 |

Overlap policy notes:

- `skip_same_symbol` is the preferred policy. It suppresses Calm A if same-symbol Normal/Stress is
  already open.
- `stress_overrides_calm` at cap 2.5% is very close to skip and does not materially change OOS.
- `stack_allowed` is diagnostic only; do not use for paper/live because MES/MNQ broker/netting
  interactions are exactly what this research is trying to avoid.

Interpretation:

- Candidate A improves the combined book at cap 5% in all three windows without worsening MaxDD.
- Cap 2.5% is more conservative, but 2026 sanity is slightly worse than the no-Calm-A base because
  it admits a small losing subset while rejecting other Calm A trades.
- Cap 5% is the best measured row, but the cap is an ATR proxy because the strategy has no stop.

Decision: Candidate A is worth carrying as a **paper/shadow add-on challenger** with default
policy `skip_same_symbol`. Use cap 2.5% for conservative paper logging, or cap 5% if the paper goal
is to measure the candidate closer to its full historical behavior. Do not call it production-ready
until a live untouched paper window exists.

#### Calm A Disaster Stop Check

Scratch artifacts:

- `scratch/calm_a_disaster_stop_probe_20260822.py`
- `scratch/calm_a_disaster_stop_probe_20260822_report.md`
- `scratch/calm_a_disaster_stop_probe_20260822.json`

Question: can Candidate A be made production-risk-clean by adding an explicit disaster stop instead
of relying on an ATR proxy cap?

Stop fill rule for LONG: if a forward bar trades through the stop, fill at the stop unless the bar
opens below the stop, in which case fill at the open.

Combined rows use the strongest current base plus Calm A with `skip_same_symbol` and Calm cap 5%.

| Window | Stop | Standalone net | Standalone PF | Standalone DD | Stop rate | Median risk | Max risk | Calm taken/rej | Combined net | Combined PF | Combined Calmar | Combined MaxDD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| floor | no_stop | +$9,718 | 1.67 | $1,720 | 0.0% | $580 | $2,062 | 335 / 7 | +$72,732 | 1.65 | 2.11 | $4,923 |
| floor | atr05 | +$8,757 | 1.58 | $1,397 | 25.8% | $116 | $412 | 342 / 0 | +$72,794 | 1.65 | 2.12 | $4,923 |
| floor | atr10 | +$7,957 | 1.49 | $1,912 | 7.7% | $232 | $825 | 342 / 0 | +$71,843 | 1.63 | 2.09 | $4,923 |
| floor | atr15 | +$9,686 | 1.67 | $1,792 | 0.6% | $348 | $1,237 | 342 / 0 | +$73,599 | 1.66 | 2.14 | $4,923 |
| floor | or_low_1tick | +$5,606 | 1.54 | $1,140 | 62.2% | $39 | $314 | 342 / 0 | +$69,622 | 1.64 | 2.01 | $4,951 |
| 2025 | no_stop | +$2,050 | 2.69 | $362 | 0.0% | $1,009 | $2,620 | 38 / 4 | +$17,881 | 2.32 | 4.63 | $3,943 |
| 2025 | atr10 | +$1,804 | 2.24 | $571 | 2.3% | $404 | $1,048 | 42 / 0 | +$17,848 | 2.28 | 4.67 | $3,896 |
| 2025 | atr15 | +$2,050 | 2.69 | $362 | 0.0% | $605 | $1,572 | 42 / 0 | +$18,093 | 2.33 | 4.74 | $3,896 |
| 2025 | or_low_1tick | +$18 | 1.01 | $788 | 61.4% | $66 | $377 | 42 / 0 | +$16,165 | 2.12 | 4.22 | $3,912 |
| 2026 sanity | no_stop | +$1,185 | 1.61 | $385 | 0.0% | $1,724 | $3,200 | 15 / 12 | +$10,132 | 1.72 | 3.72 | $4,342 |
| 2026 sanity | atr10 | +$1,185 | 1.61 | $385 | 0.0% | $690 | $1,280 | 27 / 0 | +$10,135 | 1.67 | 3.72 | $4,342 |
| 2026 sanity | atr15 | +$1,185 | 1.61 | $385 | 0.0% | $1,035 | $1,920 | 26 / 1 | +$9,779 | 1.65 | 3.59 | $4,342 |
| 2026 sanity | or_low_1tick | +$1,079 | 1.80 | $495 | 50.0% | $106 | $2,354 | 26 / 1 | +$10,108 | 1.70 | 3.71 | $4,342 |

Interpretation:

- Opening-range stop is too tight. It stops 50-62% of trades and materially cuts IS/2025 edge.
- ATR 0.5 is also too tight; it turns 2025 standalone negative.
- ATR 1.0 is viable and active enough to be a real stop, but it gives up material floor edge.
- ATR 1.5 is the best disaster-stop candidate: it creates explicit stop-risk, preserves standalone
  edge, improves combined floor/2025 versus no-stop, and does not worsen combined MaxDD.

Decision: if Calm A moves beyond paper/shadow, use **disaster stop = entry - 1.5x daily ATR** as
the first production-risk-clean candidate. Keep `or_low_1tick` rejected.

## Trade Artifacts

Canonical Normal/NKD trade dumps:

- `scratch/normal_promotion_trades_floor_20260821.json`
- `scratch/normal_promotion_trades_vault2025_20260821.json`
- `scratch/normal_promotion_trades_vault2026_20260821.json`

Canonical Stress/switch measurement scripts and reports:

- `scratch/stress_switch_full_replay_20260822.py`
- `scratch/stress_switch_full_replay_20260822_report.md`
- `scratch/stress_single_cap_probe_20260822.py`
- `scratch/stress_single_cap_probe_20260822_report.md`
- `scratch/stress_with_nkd_probe_20260822.py`
- `scratch/stress_with_nkd_probe_20260822_report.md`
- `scratch/stress_nkd_size_cap_sweep_20260822.py`
- `scratch/stress_nkd_size_cap_sweep_20260822_report.md`
- `scratch/calm_nkd_switch_vs_current_20260822.py`
- `scratch/calm_nkd_switch_vs_current_20260822_report.md`
- `scratch/calm_a_combined_replay_20260822.py`
- `scratch/calm_a_combined_replay_20260822_report.md`
- `scratch/calm_a_disaster_stop_probe_20260822.py`
- `scratch/calm_a_disaster_stop_probe_20260822_report.md`

Trade count convention:

- `trade` / `leg` means one instrument-level entry.
- `MNQ 7x` is one Stress leg with quantity 7, not seven independent observations.
- R4 basket variants can create up to four legs per signal day.

## Open Gates Before Production

1. Implement switch policy in production and audit same-symbol broker/netting behavior.
2. Verify Stress fill timing:
   - setup bar known before entry;
   - no signal-after-entry;
   - no same-bar exit leakage.
3. Re-run full replay from production signal path, not only captured artifacts.
4. Confirm Normal-R4 filter and engine gap-through fill fix are production-patched.
5. Run paper/live shadow test with actual IBKR order events:
   - Normal MNQ forced close before Stress entry;
   - Stress entry accepted/rejected after cap check;
   - Normal MNQ suppressed while Stress is open;
   - no B3 mismatch / net-zero broker state.
6. Re-check OOS concentration because Stress 2025/2026 sample is sparse.

## Current Decision

Carry forward two tracks after the repaired replay:

### Track 1 - Risk-Clean Fallback

```text
Closest risk-clean production-audit candidate:
  Normal-R4 filtered qty 1
  Stress-MNQ mnq_only_g3_q7 qty 7, cap 10%
  Current NKD/MNKD qty 1, cap 6%, no Calm-NKD switch
  Calm A PCLoc MES/MNQ add-on, ATR15 disaster stop
  Bidirectional same-symbol skip between Normal/Stress/Calm A
  Normal+Calm family cap 5.0% gross / 4.4% net
```

Measured after repaired replay:

| Window | Net | PF | Sharpe | Calmar | MaxDD |
|---|---:|---:|---:|---:|---:|
| floor 2018-2024 | +$64,903 | 1.62 | 2.34 | 1.92 | $4,845 |
| 2025 | +$13,236 | 2.00 | 2.96 | 3.09 | $4,632 |
| 2026 sanity | +$8,260 | 1.55 | 2.57 | 2.75 | $4,797 |

This is the cleaner path if the goal is to move toward production audit without waiting for a
Calm-NKD rebuild.

### Track 2 - Research-Upside Full Stack

```text
Research-upside candidate:
  Normal-R4 filtered qty 1
  Stress-MNQ mnq_only_g3_q7 qty 7, cap 10%
  Current NKD/MNKD qty 1, cap 6%
  Calm-NKD switch challenger on MNKD
  Calm A PCLoc MES/MNQ add-on, ATR15 disaster stop
  Bidirectional same-symbol skip between Normal/Stress/Calm A
  Normal+Calm family cap 5.0% gross / 4.4% net
```

Measured after repaired replay:

| Window | Net | PF | Sharpe | Calmar | MaxDD |
|---|---:|---:|---:|---:|---:|
| floor 2018-2024 | +$74,410 | 1.67 | 2.12 | 2.14 | $4,973 |
| 2025 | +$16,997 | 2.26 | 2.76 | 4.45 | $3,901 |
| 2026 sanity | +$9,288 | 1.62 | 2.47 | 3.41 | $4,342 |

This is stronger on net/Calmar, but **not stop/risk-clean yet** because Calm-NKD's risk definition
still needs regeneration using true stop-at-entry risk.

Audit scope should explicitly cover:

- Stress switch:
  - same-symbol Normal MNQ forced close before Stress entry;
  - Stress cap check before closing existing Normal;
  - Normal MNQ suppression while Stress is open;
  - no broker/netting mismatch.
- Calm-NKD switch:
  - current MNKD forced close at Calm-NKD entry;
  - current NKD suppression while Calm-NKD is open;
  - exact MNKD fill/cost/slippage accounting for forced closes.
- Calm A:
  - D-1 Calm causality;
  - prior full RTH session convention;
  - 10:00/15:55 fill feasibility;
  - no same-symbol stack with Normal/Stress;
  - ATR15 disaster stop and true stop-risk admission.
- Portfolio replay:
  - regenerate from signal path where possible, not only captured artifacts;
  - report cluster taken/rejected/halts;
  - report MaxDD deltas versus the no-Calm and no-Stress baselines;
  - keep 2026 as sanity only, not selection.

Do not label as production deploy-level until repaired production replay and broker switch audit pass.

---

## Stop / Risk Audit — 2026-08-22

> **Superseded in part.** The blockers below were repaired in the scratch replay on the same
> day and independently verified. Read the *Repair Status* table at the end of this document
> before acting on anything in this section.

Read-only audit of the combined candidate. No production file changed. Full detail and every
number below: `scratch/combined_stop_risk_audit_20260822_report.md`.

The audit rebuilt the combined replay so it could be instrumented, and refused to report
anything until the rebuild reproduced four published rows to the dollar (R4-only net $29,046
and drawdown $6,209; combined net $72,732 and drawdown $4,923) plus a cashflow ledger that sums
to the daily series to the cent. All green in all three windows.

### Verdict

**Not stop/risk-clean yet.** Normal-R4 and Stress-MNQ are clean. The blockers sit in the two
switch mechanisms and in the Calm-NKD risk definition.

### Blockers

1. **Stress settles a same-symbol Calm A position twice and leaves it open.** Under
   `skip_same_symbol` the survivor list keeps a same-symbol Calm position while the close list
   cashes it out, so it settles at the Stress entry and again at its own 15:55 exit. Floor: 4
   occurrences, duplicated cashflows −$635. For those afternoons the book really was holding a
   Calm long and a 7-lot Stress short on the same contract — the netting exposure the switch
   exists to prevent. Published floor net is not a single-settlement number.
2. **Normal-R4 can open on a contract where Calm A is already running.** The skip rule is
   one-directional and the windows overlap ~2h daily. Floor 6, 2025 1, 2026 1.
3. **The Calm-NKD switch is priced across two different NKD files.** Frozen 2024 sits exactly
   +100.0 index points above the continuous series and frozen 2025 exactly −10.0, measured over
   1.67M overlapping bars. The offset cancels inside a sleeve but not in a forced close.
   Corrected: switch value +$340 → **+$1,790** (floor), +$30 → **−$5** (2025), unchanged
   −$3,172 (2026, same file — the self-check); combined net $72,732 → **$74,182** and $17,881 →
   **$17,846**. After correction the switch's case is in-sample only and its one clean
   out-of-sample reading is sharply negative.
4. **Calm-NKD's declared risk is ~40× its real stop risk.** It uses the engine-default trailing
   chandelier on 5-minute ATR, not the fixed 2.0× daily-ATR stop the rest of the book uses.
   Median stop distance on floor is 23 index points = **4.6 ticks = $11.52**, against a $472
   declared cluster risk — which is why the cap never binds (758 admitted / 0 rejected). Win
   rate 12.9%, 87% stopped out. One extra tick of stop-fill slippage costs 17% of floor net,
   three ticks costs 50%; current NKD loses 1.6% under the same test.
5. **The new Calm cluster shares instruments and session with Normal-R4 while the guard caps
   each cluster independently.** Two 5% gross budgets on MES/MNQ in the same afternoon add with
   nothing checking the sum. The independence argument written for the NKD cluster (different
   session, low cross-correlation) does not transfer.

### Defects — fix, not blocking

6. **Max-hold exit pre-empts the armed stop.** The day loop closes at the 09:30 open before
   asking whether the resting stop was touched earlier that session. Floor: 4 of 894 armed
   max-hold exits, −$424 total, worst −$377 (M2K short, 2020-11-04: the overnight ran from 1835
   through the 1868 stop to 1943 before the cash open). Conservative direction, but it is the
   only realised-loss-over-declared-risk breach in Normal-R4 anywhere in the sample.
7. Forced-close price lookup drops a position silently if no bar is found. Zero occurrences, but
   it fails open.
8. The Calm A replay does not count Normal entries suppressed by an open Stress position — on
   floor, 7 entries worth $1,723 of forgone profit.
9. Production arms stops at **14:00**; the artifacts assume 14:05.
10. The three swing sleeves stamp entries at the *start* of the 5-minute resume bar while
    filling at its *close*. Harmless today, latent for any future sleeve in that window.
11. Two Calm A legs in the 2026 window fall on 2026-08-19, a session the artifact clip excludes.

### Confirmed clean

- **Normal-R4 stop is real and exact**: all 81 chandelier stop exits on floor sit within 0.01% of
  exactly 2.0 × daily ATR from entry. Cap charges 2.5 × daily ATR — a measured 25% conservative buffer.
- **Stress cap charges the true stop risk** (`abs(stop−entry) × $2 × 7`); confirms itself —
  largest declared risk $5,290 against a $5,000 cap, exactly one leg rejected.
- **Stress switch ordering is correct**: admission is tested against the post-close book
  *before* anything is closed, so a rejected Stress leaves Normal untouched. Exercised (1
  rejection on floor, 1 in 2026). Forced-close P&L is counted. No same-symbol Normal survives a
  Stress entry, in any window.
- **No gap-through problem** — but see the correction at the end of this document: this held
  because a stronger fill law was already applied, not because the case never arises. No stop exit
  booked at the stop price sits on a bar that had already
  opened through it: 0 of 81 / 13 / 6 chandelier exits (the handful of GAP-reason exits are the
  open-fill case and are already correct by construction). The harness's arming-instant fill fix has **zero** candidates on this
  trade set — measured through a printed funnel so the zero is a real zero, not an empty scan.
  The fix being off when the artifacts were generated changed nothing.
- **No double-stacking**: zero MNKD double-stacks, zero Stress-on-Normal overlaps, zero
  within-sleeve overlaps, in every window.
- **Causality clean in all four sleeves.** Stress uses only bars complete at 10:35 and enters at
  10:35 or later. Calm A uses the prior completed full RTH session plus today's 09:30 open and
  enters at 10:00. Both Calm gates take the strictly previous labelled day.
- **Unarmed-window exposure is covered by the buffer.** Across 980 trades holding ~23h with no
  stop in the market, not one moved further against the position than its declared cluster risk,
  and only two ever passed the stop level (both MES, worst 1.11×). Median exposure 0.14–0.20× the
  stop distance. Empirical on this sample, not structural.
- **Fill/timing clean** for Normal-R4, current NKD, Stress and Calm A: no price outside its bar,
  no signal after entry, no same-bar exit, no missing bars. Calm-NKD **could not be checked** on
  a common basis because of blocker 3 — not passed, not failed, not run.
- **Realised loss vs declared risk**: the only breaches besides the max-hold case are seven
  trades at ratios 1.01–1.03, all exiting exactly at their stop. That overshoot is the execution
  cost, which sits outside the declared number by definition in every sleeve.

### One thing to adopt with eyes open

Giving Calm A the 1.5 × daily ATR disaster stop makes the cap charge a true stop risk instead of
a proxy — and that true risk is *smaller* than the proxy (median $348 vs $580 on floor), so the
same 5% budget **admits more trades**: 335/7 → 342/0 on floor, 38/4 → 42/0 in 2025, and 15/12 →
26/1 in 2026. The stop itself fires twice in 421 trades and never outside the floor window; 2025
and 2026 net are identical with and without it, to the dollar. The change is almost entirely to
the admission arithmetic, not to the protection. It replaces a made-up number with a real one,
which is right — but it loosens the sleeve rather than tightening it.

### Remaining non-risk items before a production patch

- Regenerate the full replay from the production signal path, not captured artifacts, and run a
  live paper window with real broker events (already on the Open Gates list).
- **Nothing here is wired live.** There is no `roska4_calm` cluster in production, no
  forced-close or suppression machinery in the runner, and no Calm-PCLoc or intraday
  Stress-detector code path. The production arming table covers exactly two clusters. So the
  switch semantics have never been exercised against a broker.
- Stress out-of-sample evidence is 3 legs in 2025 and 4 in 2026, and its adverse excursion
  routinely reaches 96% of the declared stop risk (p90, floor) with a worst single-leg excursion
  of $3,381. Concentration and slippage sensitivity on that sleeve stay open.
- The MNKD contract in use expires **2026-09-04**. Both NKD sleeves depend on it.

---

## Repair Status — independently verified 2026-08-22

The Stop / Risk Audit section above describes the state **before** the repaired replay. This
table is the current state. Detail: `scratch/combined_repaired_verify_20260822_report.md`.

The repaired replay reports its own `double_booked = 0`; a counter a script keeps about itself is
not evidence, so the same control flow was rebuilt with separate instrumentation. Gate: the mirror
must reproduce the repaired script's net, worst drawdown and cashflow-ledger sum to the cent.
**15 of 15 window × policy rows pass.** The repaired script also re-runs byte-identical, and its
internal accounting closes (`attempted = taken + rejected + suppressed + halted`) in all fifteen rows.

| # | Item from the audit above | Status |
|---|---|---|
| 1 | Stress double-settles a same-symbol Calm A position | **Repaired, verified** — positions entered = positions settled in 15/15 runs; 0 settled twice, 0 never settled |
| 2 | Normal-R4 opens into an existing Calm A | **Repaired, verified** — 0 same-symbol overlaps in 15/15 runs, previously 10 / 1 / 1 |
| 3 | Calm-NKD switch priced across two NKD series | **Repaired as a stopgap, verified** — switch value matches the independent correction to the dollar (+$1,790 / −$5 / −$3,172); offset re-derived from today's parquets and still exact |
| 4 | Calm-NKD declared risk ≈ 40× its true stop risk | **Not repaired** — acknowledged; this is what keeps the full stack out of production audit |
| 5 | Normal and Calm capped independently on shared contracts | **Repaired and sized** — see below |
| 6 | Max-hold exit pre-empts the armed stop | **Not repaired** — engine level, −$424 on floor over seven years, conservative direction |
| 7 | Forced-close price lookup drops a position silently | **Not repaired** — 0 occurrences in 15/15 runs, still fail-open, and now more reachable because Stress removes Calm A too |
| 8 | Normal suppression by Stress was uncounted | **Repaired** — counted with its P&L; floor rises from 7 to 17 suppressed entries |
| 9 | Production arms at 14:00, artifacts assume 14:05 | **Not repaired** — needs artifact regeneration |
| 10 | Swing entries stamped at the start of the 5-minute bar, filled at its close | **Not repaired** — latent, no effect on current sleeves |
| 11 | Two Calm A legs on a session the artifact clip excludes | **Not repaired** |

### Three corrections to the audit above

**Item 5 was real but smaller than I implied.** I wrote that two 5% budgets on the same contracts
"add to 10% with nothing checking the sum". Measured continuously at every event instant, combined
Normal + Calm gross peaked at **6.86% / 7.82% / 7.53%** — never near 10%. Median is only 1.2–2.1%
and the ninetieth percentile 3.7–3.9%, so it is a tail, not a norm. The tail is still worth
removing: 7.82% is 56% above the ceiling Normal alone is held to. The 5.0%/4.4% family cap holds
it to 4.90% / 4.96% / 4.84% and costs $878 / $116 / $491 of net.

**The family cap is an admission gate, not a maintained limit.** No family entry was ever admitted
above it — admission-time net peak on floor is exactly 4.40% against a 4.4% cap. But realised net
drifted to **4.89% on 7 occasions** in the floor window: 5 straight after a family position exited
(dropping a short from a long-heavy book raises the net) and 2 observed at an unrelated admission
on a state that had already drifted. Zero breaches in 2025 and 2026. This is not something the
family cap introduced — every cluster cap in the guard behaves this way, including the pre-existing
4.4% net cap on Normal alone — but "4.4% net" should not be read as a guarantee about carried
exposure. Measured overshoot: +0.49 percentage points, 11% over.

**Family cap 7.5%/7.5% is a no-op on the floor window.** Zero family rejections, and every column
— net, PF, Sharpe, Calmar, drawdown, taken and rejected — identical to running with no family cap,
peak still 6.86%. On 2026 it reads better than the tighter cap only because it happened to reject
three legs that lost, and 2026 is a sanity window. **5.0%/4.4% is the only setting that constrains
the tail in all three windows.**

### Two wording fixes for the tracks above

- Both tracks say "bidirectional same-symbol skip between Normal/Stress/Calm A". For Calm A versus
  Stress it is **not a skip**: Stress **force-closes** an open same-symbol Calm A position, four
  times per floor window, at the Stress entry price. That is an order sent to the market, and the
  broker/netting audit has to cover it.
- "Risk-clean fallback" is accurate **at the replay level**. Items 6, 9 and 10 sit below the
  replay — in the engine and in the captured artifacts — and are untouched. None is large, but the
  label should carry the qualifier rather than imply the whole chain is cleared.

### Still fragile even though it measures correct

The NKD price offsets are a hardcoded literal dictionary in the repaired replay. I re-derived all
three from the parquets as they stand today (floor +100.0, 2025 −10.0, 2026 0.0, each a single
value across every overlapping bar) and they match exactly. Rebuild or re-roll either NKD parquet
and the literal keeps its old value while the data moves underneath it, with nothing to catch it.
Derive it at run time — or do the real fix, regenerating Calm-NKD from the same file the
current-NKD artifact uses, which is already the plan for item 4.

---

## Calm-NKD Regeneration — resolved 2026-08-22, Track 2 CLOSED

Full detail: `scratch/calm_nkd_regen_same_basis_20260822_report.md`.

Calm-NKD was regenerated on the current sleeve's basis: the frozen NKD file named in each window's
own arguments, ema 10 / mult 2.5, and the fixed stop at entry ± 2.0 × daily ATR armed the next
session — i.e. true stop-at-entry risk. Anchor gate: with the current sleeve's regime labels the
harness must reproduce the artifact's MNKD book exactly.

**Anchor passed in all three windows** — 228 / $3,898.30, 31 / $2,203.04, 26 / $4,292.17, matching
every trade's price, exit reason and P&L. It failed twice first; getting onto the artifact's basis
needed four settings, not two. Two of them (`allowed_regimes` forced to `["Normal"]`, and the SPY
short gate) are applied globally by the artifact generator, read as Ro-4 concerns, and are documented
nowhere in the NKD sleeve's own configuration — yet they reach it.

### Result: fail

| ema | floor 2018-2024 | 2025 | 2026 sanity |
|---:|---:|---:|---:|
| 5 | **−$509** | +$2,556 | +$3,399 |
| 10 | **−$3,556** | +$2,778 | +$1,765 |
| 15 | **−$1,545** | +$2,948 | +$1,330 |
| 20 | **−$1,963** | +$3,416 | +$266 |

Every ema is negative in-sample. At the sleeve's own ema of 10: 205 trades, PF 0.85, win rate 45.9%,
and **one positive year out of seven** (2023 +$1,153; 2018/19/20/21/22/24 all negative).

Stop distance verified at exactly 2.0 × daily ATR on every stop exit, so the risk model half of the
ask succeeded. It is the edge that is not there once the risk model is honest.

`chandelier_atr_mult` is **inert** on this basis — mult 2.0, 2.5 and 3.0 give byte-identical trade
lists in all three windows, because the stop comes from `stop_basis` and the ratchet is off. The old
six-variant grid collapses to ema alone; three of the six were the same run.

### Where the old +$7,156 came from

The two sleeves are genuinely complementary, not redundant: on floor the current sleeve takes 228
entries, every one on a D-1 Normal day, and Calm-NKD takes 205, every one on a D-1 Calm day —
**intersection zero**. The design intent was sound. But the edge on those days was never the Calm
gate; it was the stop. The original variant's 2.5 × five-minute-ATR ratcheting chandelier gave a
median stop 23 index points wide — 4.6 ticks, $11.52 — stopping out 87% of trades at roughly the
round-turn cost and letting the other 13% run. Swap in the sleeve's real stop and the win rate goes
12.9% → 45.9% and floor net goes +$7,156 → −$3,556.

### Decision

Per the rule set before the run: **fail → Track 2 closed, commit to Track 1.**

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

Item 4 of the repair status table (Calm-NKD declared risk ≈ 40× true stop risk) is now **resolved by
removal**: the sleeve is dropped, not fixed. Items 6, 9 and 10 remain open and sit below the replay.

### Correction to the Stop / Risk Audit above

Section 3 of that audit concluded **"the gap-through fix is a no-op on this trade set."** That was
wrong. The post-hoc correction was switched off because a *stronger implementation of the same law
was already on* one layer down: the artifact generator marks every bar gap-eligible, so any stop the
market opened beyond is relabelled a gap exit and filled at that bar's open. My check scanned stop
exits asking whether the bar had already opened through the stop — and every such case had already
been converted before the scan saw it. **The check could not have gone red.** I printed its funnel as
evidence that the zero was real; the funnel measured the residual after the fix, not the absence of
the problem.

The direction reverses: the artifacts are **more** conservative on stop fills than the production
engine, which only fills at the open after a real time break of more than fifteen minutes. Measured
on the NKD sleeve by running the anchored configuration both ways — floor **−$5.36** (4 exits
relabelled), 2025 **$0.00**, 2026 **−$3.21** (1 exit). The Ro-4 side carries one gap exit on floor
and one in 2026, not separately priced.

The finding that mattered still stands — no stop in the candidate book is filled at a price the
market had already passed — but it stands because the conservative law was applied, not because the
situation never arises.

---

## Calm-NKD Tight-Stop as a Standalone Strategy — REJECTED 2026-08-22

Full detail: `scratch/calm_nkd_tight_stop_audit_20260822_report.md`.

The previous rejection only killed Calm-NKD as a same-risk-model replacement for the current NKD
sleeve. This audit re-opened it as a strategy in its own right, on its own tight 5-minute chandelier
stop, with no requirement to match the current sleeve. It was tested on its own terms and **fails on
measurement**.

**Anchor passed exactly** — all six original variants rebuilt trade-for-trade in all three windows,
including the headline `ema5_mult2.5` floor book of 550 trades / **+$7,156** / PF 1.55.

### Why it is rejected: the edge is impossible fills, not tail capture

The engine checks a carried position's stop **once per calendar day**, at the start of that day's bar
group. For a Tokyo-timezone frame that boundary is **midnight JST — the middle of a continuously
trading session**. A position entered at 14:00–15:55 JST is not stop-checked again for eight to ten
hours. By then price has usually walked past a 22-point stop; because the market never stopped
trading, no time break precedes that bar, the gap-fill rule does not engage, and the engine books
the exit **at the stop price nobody could have got**.

- **290 of 471** stop exits on floor are booked at a price the bar had already opened beyond, worth
  **$13,297** — against a total net of $7,156. 248 of them land at 00:00–00:01 JST, and 228 have a
  previous bar exactly one minute earlier.
- Worked case: 2018-03-23, bar range 20,150–20,165, exit booked at **20,463.2** — 313 points outside
  the bar.

Three independent measurements agree, two of them to the dollar:

| | floor ema5 |
|---|---|
| impossible-fill benefit measured directly | **$13,297** |
| rerun with the fill made possible: net moves | +$7,156 → **−$6,141** (delta **−$13,297**) |
| trades whose adverse move exceeded their own stop | **519 of 550 (94%)**, median 3.62× the stop |

With possible fills, **every ema is negative on floor and on 2025**: floor −$6,141 / −$11,737 /
−$9,833 / −$8,860; 2025 −$1,545 / −$2,381 / −$2,668 / −$3,429. PF 0.53–0.77.

### The other pre-stated rejection tests

- **Slippage** (on the as-shipped book): floor net −17% at +1 stop tick, −33% at +2, −50% at +3.
- **Concentration**: top five trades = 53.7% of floor net; 2021 alone = 48.9%. In 2025 the top five
  winners exceed the entire net.
- **Cap**: median true risk $11.30 against a $3,000 budget, and the engine holds at most one position
  at a time. The cap cannot bind at any minimum charge up to $300; making it bind would need roughly
  $3,000 per trade — 265× true risk, with no derivation behind it.
- **Plateau**: ema5 is the top floor cell and its neighbour ema10 returns 49% of it, so the ±30%
  neighbour rule is not met. Rankings also reorder across all three windows.

Portfolio integration was **not run** — the specification gates it on the standalone passing.

### What this also settles

The old comparison that made Calm-NKD look better than the current sleeve was never like-for-like on
the fill law either: the current sleeve's artifact was generated with every bar treated as
gap-eligible, and the Calm-NKD probe was not. That difference alone is worth $13,297 on floor.

### If anyone wants to revisit tight-stop NKD

The obstacle is structural, not a parameter. Any stop tighter than the typical eight-to-ten-hour move
between the Tokyo afternoon entry and midnight JST **cannot be evaluated by this code path at all**.
A same-session stop harness exists (`model_sameday_stop.run_loop` with `same_day_stop=True`) which
makes the stop live from the fill; that is the only path that could measure it honestly. No promise
that it would pass — the single row that survives possible fills is 2026 ema10 on 40 trades, and
2026 is a sanity window.

**Committed stack is unchanged — Track 1:** Normal-R4 filtered qty 1 · Stress-MNQ `mnq_only_g3_q7`
qty 7 cap 10% · current NKD/MNKD qty 1 cap 6% · Calm A PCLoc MES/MNQ with the ATR15 disaster stop and
true stop-risk · bidirectional same-symbol skip with Stress force-closing same-symbol Calm A ·
Normal+Calm family cap 5.0% gross / 4.4% net.

---

## Calm-NKD Widened Live-Stop Excavation - REJECTED 2026-08-22

Full detail: `scratch/calm_nkd_widened_live_stop_20260822_report.md`.

Question: after rejecting the old Calm-NKD tight stop for impossible fills, can a wider stop rescue
the idea if the stop is live immediately after entry?

Method:

- Gate: D-1 Calm, presented to the swing signal as `Normal`.
- Instrument: MNKD.
- Stop semantics: live from the bar after entry, checked on 1-minute bars.
- Tested stop families:
  - old initial stop widened by 1.5x / 2x / 3x / 4x / 6x / 8x;
  - daily ATR stop at 0.25x / 0.35x / 0.50x / 0.75x / 1.00x.
- EMA sweep: 5 / 10 / 15 / 20.

Result:

- Every printed floor row through width 8x and daily ATR 0.75x was negative.
- The only baseline row positive on both floor and 2025 was `daily_atr 1.0 / ema20`:

| Window | Trades | Net | PF | Calmar | MaxDD |
|---|---:|---:|---:|---:|---:|
| floor 2018-2024 | 261 | +$4,363 | 1.19 | 0.28 | $2,213 |
| 2025 | 36 | +$544 | 1.10 | 0.31 | $1,931 |
| 2026 sanity | 23 | -$1,111 | 0.87 | -0.60 | $3,450 |

Concentration:

- floor top 5 winners = 87% of net.
- 2025 top 5 winners = 6.77x total net.

Verdict: **reject**. Widening the stop removes the impossible-fill issue, but it does not create a
deployable sleeve. The only survivor is too thin, concentrated, and fails 2026 sanity. Calm-NKD is
closed, not pending.

Track 1 remains the current candidate.

---

## Track 1 — Production Feasibility Audit — 2026-08-22

Full detail: `scratch/track1_production_feasibility_audit_20260822_report.md`.

### Verdict: **BLOCKED PENDING PATCH** — measurement passes, wiring does not

Gate first: the instrumented replay reproduces Track 1 to the cent in all three windows
($64,902.91 / $4,845.31 · $13,236.11 / $4,631.53 · $8,259.85 / $4,797.44), and the event counts close
against the sleeve tallies without slack.

**Nothing in this audit found a new measurement blocker.** On the evidence Track 1 is a legitimate
production patch candidate. What blocks it is that the patch is bigger than expected.

### The finding that changes the plan

The expectation was that Calm A, Stress and the switch are not wired. True. But **Normal-R4 — the
largest contributor — is also not what production runs today**:

| | Track 1 | production today |
|---|---|---|
| EMA | 50 | **30** (`futures/basket.py: SWING_TF_PARAM`) |
| Stop | entry ± **2.0 × daily ATR**, fixed | **engine chandelier** (2.5 × 5-minute ATR at entry, daily-ATR trail) |
| Ratchet | off | **on** |
| Arm time | 14:05 | **14:00** |
| Cap risk convention | 2.5 × daily ATR × pv | same ✓ |
| R4 context filter, SPY short filter | required | **do not exist** |

`run_live_day.py` builds `SwingTFEngine()` with defaults; no config reaches it. Nothing in production
imports `model_sameday_stop` or `scratch.harness`. So Track 1 is **not** an additive patch — it changes
a sleeve that is already sending orders, and that deserves its own before/after gate rather than
riding in on a Track 1 patch.

### Signal-path regeneration — reproduced byte for byte

`normal_promotion_regen_audit` (which drives `deploy_sim.main()` end to end) was re-run from scratch.
All three promotion artifacts reproduced with **matching sha256**, and the script's own internal
anchors passed in every window ($33,176 / $6,857 / $6,743). That script overwrites those shared files
in place, so they were snapshotted first, this audit was pointed at the untouched snapshot, and the
originals were restored — the shared files end the session exactly as they began. **No reproduction
mismatch to attribute.**

### Measurement results — all clean

- **Fill audit, all four sleeves, all three windows**: 0 outside-entry-bar, 0 outside-exit-bar,
  0 signal-after-entry, 0 same-bar exit, **0 impossible stop fills**. (Two missing lookups: the two
  Calm A legs on 2026-08-19, a data-clip boundary.) This is the same test that killed the Calm-NKD
  tight-stop candidate at 290 of 471 exits; Track 1 has zero.
- **Settlement exact**: floor 1,160 entered / 1,160 settled, 0 twice, 0 never. Same in 2025 (128/128)
  and 2026 (91/91).
- **Position invariants**: 0 violations — no same-symbol stack, no opposite-direction overlap, at any
  instant, re-checked after every entry and every force-close.
- **Cap admission tested before any close**: a rejected Stress performs no force-close. One such
  rejection on floor, one in 2026.
- **Item 9 (14:00 vs 14:05) closes at exactly zero.** For every Track 1 swing position, the stop was
  never touched inside the 14:00–14:05 window, in any window. The five-minute discrepancy carries no
  measurement debt; fix it when the artifacts are next regenerated.
- **Item 6 (max-hold pre-empts the armed stop)**: 4 events on floor, **−$423.54**, 0 in 2025/2026.
  Conservative direction.
- **Item 10 (5-minute timestamp)**: 0 cases on floor, 0 in 2026, **2 in 2025** — a MYM swing entry
  stamped 15:50 (filling 15:55) against two Calm A exits at 15:55 on 2025-08-04. Replay is the
  conservative side. Harmless today; becomes a real defect if any future sleeve trades 14:00–15:55.

### Switch shape, measured

| Window | force-closes | victims | instrument | booked P&L on forced legs | suppressions | breaker halts |
|---|---:|---|---|---:|---:|---:|
| floor | **14** | 10 Normal-R4, 4 Calm A | all MNQ | −$6,072.36 | 22 | 2 |
| 2025 | **1** | 1 Normal-R4 | MNQ | −$1,744.24 | 4 | 0 |
| 2026 | 0 | — | — | — | 1 | 0 |

Roughly two switches a year, every one on MNQ.

### Caps

Carried peaks against cap: family 4.90/4.89% vs 5.0/4.4 (floor), Stress 8.36–8.54% vs 10,
NKD 4.21% floor but **5.92% in 2026 against a 6% cap** — within 0.08 points, with 2 rejections. The
NKD module's own docstring already flags that at 2026 Nikkei volatility the 6% cap clears by only
~5%; Track 1 inherits that.

**The family cap is an admission gate, not a maintained limit.** No family entry was ever admitted
above cap — admission-time family net peak on floor is exactly 4.40% against 4.4%. Carried net drifts
to 4.89% on 7 occasions, five straight after a family position exits. Not introduced by the family
cap; every cluster budget in the guard behaves this way.

### Wiring — the blockers

1. `roska4_calm` does not exist anywhere; the guard has **no family/aggregate concept at all**, and
   the family cap is what holds the shared MES/MNQ tail from 6.86–7.82% down to under 5%.
2. Calm A signal, Stress intraday detector, R4 context filter and SPY short filter: **none exist**.
3. **Close-confirm-then-enter exists but only inside the contract-roll path**
   (`ibkr_broker._handle_rollover`: close → poll to done against a 120s deadline → verify fill → open
   against a 30s deadline → abort untouched on failure). Worst case 150s, comfortably inside the
   10:35–12:30 Stress window. But it is bound to same-instrument, same-direction, same-size, identity
   preserved — while a Stress switch flips direction, changes size 1→7, and crosses clusters.
4. **Stop-cancel ordering is backwards in the one force-close path that exists.**
   `run_maxhold_exit` sends the CLOSE first and cancels the stop after. For a 09:30 max-hold exit that
   window is usually harmless. For the Stress switch it is not: the detector fires precisely when all
   four instruments are below open and VWAP and gapping down — the exact conditions under which a
   resting sell-stop beneath a Normal MNQ long is most likely to fire, opening a fresh short on top of
   the seven-lot Stress short being entered.
5. **No continuous-monitor execution shape.** Track 1 needs three new slots (10:00 Calm A entry,
   15:55 Calm A and Stress exits) **plus a monitor from 10:35 to 12:30** for the Stress entry, which
   fires on a low break at an unknown minute. Every existing slot is one-shot.
6. **No telemetry for any of it.** `FORCE_CLOSE`, `CANCEL_STOP`, `AWAIT_CLOSE_CONFIRM`, `SUPPRESS`,
   and a `family_cap` reject reason have no counterpart in the runner. A live switch would appear as
   an unlinked close and entry, and a suppressed entry as nothing at all.

Files that would need patching: `net_exposure_multi.py`, `runner.py`, `signal_layer.py`,
`run_scheduler.py`, `ibkr_broker.py`, `deploy_sim.py`, plus new modules for the two signals, plus the
Normal-R4 sleeve parameters themselves.

### Recommended sequencing — cheapest risk first

1. Land the guard's family-cap concept and the switch telemetry **before** any new sleeve.
2. Generalise the roll's close-confirm primitive and fix the cancel-before-close ordering — both are
   wanted regardless of Track 1.
3. Treat the Normal-R4 parameter change as a **separate, individually gated** change.
4. Wire Calm A before Stress: Calm A is a single-shot 10:00 entry that fits the existing slot shape;
   Stress needs the continuous monitor that does not exist.

Until at least the first three land, Track 1 is **paper/shadow only**.
