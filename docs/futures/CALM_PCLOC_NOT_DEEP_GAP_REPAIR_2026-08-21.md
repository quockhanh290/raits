# Calm PCLoc Not-Deep-Gap Repair Note

Date: 2026-08-21.

Scope: address the actionable items from `CALM_PCLOC_NOT_DEEP_GAP_AUDIT_2026-08-21.md` without
touching production code.

## Verdict

Status remains **PAPER/PILOT ONLY**.

The repaired candidate is:

`lag1calm_pcloc_bottom_down_long_e1000_x1555__MES_MNQ__not_deep_gap`

Spec:

- D-1 Calm only.
- MES and MNQ only.
- LONG only.
- Prior full RTH session close location in bottom third.
- Prior full RTH session return <= 0.
- Entry at 10:00 bar open.
- Exit at 15:55 bar open.
- Skip if current RTH open gaps more than 1.0% below prior full RTH-session close.
- No MYM.
- No volume gate.
- No SPY RV cap.
- No recursive instrument pruning.

## Repair 1: Prior RTH Session Convention

Audit found that the generator and shape/gap overlay used two different prior-session conventions
around half-days. The scratch probe `scratch/calm_causal_pcloc_shape_gap.py` now matches the causal
excavation convention:

- A futures RTH day can become a prior session only if it has a 15:55 bar.
- Half-days are skipped as prior close/range sources.
- The artifact now includes `prev_session_day` provenance for shape/gap features.

Effect:

| Window | Before repair | After repair | Read |
|---|---:|---:|---|
| IS 2018-2024 | 349 / +$9,718 / PF 1.67 | 349 / +$9,718 / PF 1.67 | unchanged |
| 2025 | 44 / +$2,050 / PF 2.69 | 44 / +$2,050 / PF 2.69 | unchanged |
| 2026 sanity | 29 / +$757 / PF 1.32 | 28 / +$1,185 / PF 1.61 | half-day-prior loss skipped |
| Pooled sanity | 73 / +$2,806 | 72 / +$3,235 / PF 2.02 | now positive bootstrap p05 |

Repaired pooled sanity bootstrap for `not_deep_gap`:

| Trades | Days | Net | PF | p05 | p50 | p95 | p_pos |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 72 | 49 | +$3,235 | 2.02 | +$53 | +$3,231 | +$6,392 | 95.4% |

This improves the sanity read, but it does not erase the audit concern that 2025 has already been
looked at many times across the Calm research program.

## Repair 2: MYM Exclusion Language

Do not phrase the pilot as "drop whichever instrument fails p < 0.05". That rule would invite
recursive pruning.

Pilot scope is instead:

- MES/MNQ are the chosen liquid index pair for a Calm paper pilot.
- MYM is excluded because it is not needed for pilot diversification and had weak IS contribution:
  low average trade, low PF, only 3/7 positive IS years, high cost drag, and negative IS bootstrap
  p05.
- No further per-instrument optimization is allowed inside this candidate.

## Remaining Blockers

Still not deploy-level:

- 2025 OOS has only 29 trading days after the filter.
- The Calm research program has already produced many 2025 reads, so the 2025 p-value is not a
  clean single-test confirmation.
- IS contribution is concentrated in 2023-2024 plus a four-trade 2022 year.
- A clean paper-forward window is still required.
- Combined risk with Normal core and Stress hedge is unresolved, especially netting when Calm LONG
  and Stress SHORT can both fire intraday.

## Pilot Risk Defaults For Next Stage

Use these as defaults for the next scratch integration, not as production code:

- Size using 4 ticks/side cost stress.
- Max 1 Calm sleeve position until combined netting is measured.
- If both MES and MNQ fire on the same day, test max 1 vs max 2 in scratch before enabling both.
- Explicitly define netting with Stress hedge before any live capital:
  - either net same-index-family exposure,
  - or let Stress override Calm on the affected instrument/day,
  - or run Calm as paper-only while Stress remains live.

Next required work: deploy-level scratch integration against current Normal+Stress research system,
with Calm marked as paper/pilot and with net exposure reported.
