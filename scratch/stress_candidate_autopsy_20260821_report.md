# Stress Candidate Autopsy - 2026-08-21

Scratch-only synthesis. No production code modified.

Purpose: explain why the Stress candidates failed, separating timing/causality,
OOS instability, WFO/concentration, slippage, and portfolio/broker interaction.

Artifacts inspected:

- `scratch/stress_mid_legacy_status_20260821_report.md`
- `scratch/stress_intraday_static_candidate_audit_20260821_report.md`
- `scratch/stress_intraday_1015_causal_floor_20260821_report.md`
- `scratch/stress_intraday_1015_causal_oos_20260821_report.md`
- `scratch/stress_new_hypothesis_floor_20260821_report.md`
- `scratch/stress_new_hypothesis_oos_20260821_report.md`
- `scratch/stress_new_hypothesis_pass2_floor_gap_20260821_report.md`
- `scratch/stress_new_hypothesis_pass2_floor_late_20260821_report.md`
- `scratch/stress_new_hypothesis_pass2_oos_20260821_report.md`
- `scratch/stress_as_filter_floor_20260821_report.md`
- `scratch/stress_as_filter_oos_20260821_report.md`

## Candidate Failure Matrix

| candidate | best-looking evidence | primary failure | why | verdict |
| --- | --- | --- | --- | --- |
| STRESS_MID legacy | 2025 lag1 +$3,998 PF 3.13 | not live/paper clean | floor collapses under lag1 to +$1,313 PF 1.14; 10:15 bar known at 10:20; 2026 lag1 -$779; live cron disabled by netting risk | disable |
| liquidation1020 as-measured | floor +$10,982 PF 1.27; 2025 +$6,952 PF 2.14; 2026 +$2,776 PF 1.57 | lookahead timing | uses 5m bar stamped 10:20 and enters 10:20; that bar is 10:20-10:24 and known at 10:25; signal_after_entry = all trades | discard headline |
| liquidation1020 causal 10:25 | 2025 +$4,088 PF 1.65; 2026 +$1,743 PF 1.31 | thin floor + overlap | floor only +$3,411 PF 1.08; 3x slippage leaves about +$959; swing opposite overlap 168/692, 113 conflict days | reject sleeve |
| causal1015_b4_rr2_x1555 | 2025 +$5,322 PF 1.80 | no floor edge / 2026 fail | floor +$1,229 PF 1.03; 2x slip +$42, 3x slip -$1,145; 2026 -$1,754 PF 0.68 | reject |
| causal1015_b3_rr2_x1555 | floor +$7,227 PF 1.11; 2025 +$4,955 PF 1.49 | weak WFO / 2026 fail | PF only 1.11 despite 1099 trades; WFO final4 -$1,064; 2026 -$1,188 PF 0.88; broad rule includes weak/chop days | reject |
| late_break_1100_b3_rr2_x1555 | floor +$4,916 PF 1.20; 2025 +$2,182 PF 1.37; 3x floor slip still +$3,404 | regime decay / WFO fail | 2023 -$746, 2024 -$1,540, 2026 -$654 PF 0.86; WFO floor total -$650 despite positive standalone row | research clue only |
| midday_expansion_1200_b3_rr2_x1555 | floor +$3,448 PF 1.21, MaxDD $1,791 | OOS contradiction | 2025 -$187 PF 0.96 and 2026 -$947 PF 0.76; floor edge does not transfer | reject |
| gapdown_break_1030_b3_rr2_x1555 | floor +$1,776 PF 1.17; 2025 +$781 PF 1.90 | too sparse / subtype contamination | 2026 -$253 PF 0.69; WFO floor -$51; plain gapdown loses -$2,116 while gapdown-full-breadth wins +$3,892 | taxonomy clue only |
| gapdown_break_1130_b3_rr2_x1555 | 2026 +$1,513 PF 14.91 | sample illusion | 2026 has only 3 trades; floor +$306 PF 1.04; 2025 -$1,477 PF 0.20; 3x floor slip negative | reject |
| vwap_reject_1200_b3_rr2_x1555 | floor PF 1.40 | no sample | floor only 17 trades / +$161; no OOS trades in pass2 | reject |
| late_day_break_1400 | small positive 2026 rows | negative floor | floor b3 -$236 PF 0.93, b4 -$933 PF 0.63; OOS sample too small to override floor | reject |
| Stress-as-filter for Calm | Calm 10:00 union filter floor +$3,889 delta; 2026 +$1,124 delta | not a Stress sleeve | works by skipping Calm longs on stress-detector days; cannot be called Stress alpha; needs Calm protocol/WFO | promising filter clue |
| Stress-as-filter for Normal | 2025 improves +$1,805 | not portable | floor skips +$10,575 of profitable Normal trades; 2026 skips +$4,070 and turns Normal kept net negative | reject global filter |

## Failure Themes

| theme | affected | diagnostic | lesson |
| --- | --- | --- | --- |
| Timing mirage | liquidation1020 as-measured, STRESS_MID legacy interpretation | bar used for signal is not known at claimed entry time | all intraday Stress signals must declare known_time and enter strictly after it |
| Lag-0 regime lookahead | daily-label Stress sleeves, STRESS_MID legacy | same-day HMM label uses D close; lag1 cuts edge materially | Stress label can be used only as D-1 state unless intraday detector is independent of daily close |
| Single-episode dependence | daily-label WFO, 2025/2026 gap candidates | one event/window creates most of the apparent net | event-cluster concentration gate is mandatory |
| Short hedge is too late or too noisy | causal1015, late_break, midday_expansion | floor PF hovers 1.03-1.21 and OOS alternates sign | futures short sleeve is not robust enough as standalone alpha |
| Broker/netting blocker | STRESS_MID, liquidation1020, most short sleeves on MNQ/MES | same-symbol opposite positions collide with swing/Calm and IBKR net position view | do not spend broker plumbing on a sleeve that fails causal WFO |
| Filter specificity | Stress-as-filter | helps Calm longs, hurts Normal | Stress detector is context-specific risk-off, not an account-wide kill switch |

## What Actually Survived

- No traded Stress sleeve survived as paper/deploy candidate.
- `late_break_1100_b3_rr2_x1555` survived only as a research clue: wait for post-11:00 continuation instead of shorting the first liquidation print.
- `gapdown-full-breadth` survived only as event-quality taxonomy: gapdown alone is bad, gapdown plus full cross-index stress is better.
- The only constructive branch is **Calm-specific Stress filter**: use stress detectors to skip Calm lower-third longs, not to short futures.

## Recommended Next Gate

Stop Stress sleeve work. Next valid work item is a Calm protocol:

1. Base rule: `openloc_lower_third_long_e1000_x1555`.
2. Candidate filters only: `late_break_1100_b3_days`, `gapdown_full_breadth_1030_days`, and their union.
3. Train/select on floor folds only.
4. Test 2025 and 2026 without tuning.
5. Reject if filter helps only 2026 or worsens combined Normal+Calm account MaxDD.
