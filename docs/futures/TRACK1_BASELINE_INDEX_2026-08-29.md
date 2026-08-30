# Track 1 — Canonical Baseline Index

**Route:** `track1_candidate` · **Compiled:** 2026-08-29 · **Status:** shadow only, orders impossible

This is the file to quote from. The repo holds **558** baseline-like Track 1 files and many of
them contain real numbers that were never the official ones — measured variants, rejected
research, superseded apparatus. Quoting one of those as "the baseline" is the failure this index
exists to prevent.

**Rule:** if a number is not in §A, §B or §C below, it is not a Track 1 baseline. Check §E before
citing any other file.

---

## A. Historical reference baseline

> **Reference only. Includes same-day Swing. Same-day Swing is not live-tradable.**

The same-day regime label is computed from the session's own 16:00 close. The Swing window is
14:05–15:55, so that label **does not exist when the sleeve decides**. These numbers are real and
reproduced; they are simply not attainable.

**Full stack** — `repaired_mechanics_family_cap_5_44`

| window | net | PF | Sharpe | Calmar | MaxDD |
|---|---:|---:|---:|---:|---:|
| floor 2018–2024 *(in-sample)* | **+$74,410** | 1.67 | 2.12 | 2.14 | $4,973 |
| 2025 *(OOS)* | **+$16,997** | 2.26 | 2.76 | 4.45 | $3,901 |
| 2026 *(OOS, through 2026-08-19)* | **+$9,288** | 1.62 | 2.47 | 3.41 | $4,342 |

**Risk-clean** — `risk_clean_no_calm_nkd_family_cap_5_44`

| window | net | PF | Sharpe | Calmar | MaxDD |
|---|---:|---:|---:|---:|---:|
| floor 2018–2024 *(in-sample)* | **+$64,903** | 1.62 | 2.34 | 1.92 | $4,845 |
| 2025 *(OOS)* | **+$13,236** | 2.00 | 2.96 | 3.09 | $4,632 |
| 2026 *(OOS, through 2026-08-19)* | **+$8,260** | 1.55 | 2.57 | 2.75 | $4,797 |

## B. Live-tradable selected paper baseline

> **Selected paper baseline by operator decision. Swing uses causal D-1 old/effective ema=50.
> Swing inclusion is operator risk acceptance, not evidence promotion.**

| window | full stack | risk-clean |
|---|---:|---:|
| floor 2018–2024 *(in-sample)* | **+$66,796** | **+$57,289** |
| 2025 *(OOS)* | **+$16,181** | **+$12,419** |
| 2026 *(OOS, through 2026-08-19)* | **+$8,105** | **+$7,077** |

### Swing — two different numbers, and they are not interchangeable

This is the single most misquotable pair in the whole record.

| window | Swing **cluster P&L** | Swing **marginal** vs no-Swing control |
|---|---:|---:|
| floor | **+$18,429** | +$17,382 |
| 2025 | **+$3,906** | +$3,804 |
| 2026 | **−$464** | **−$626** |

- **Cluster P&L** is what the Swing sleeve itself earned. The full stack is exactly the sum of
  its four clusters, so this is an accounting split.
- **Marginal** is what removing Swing actually costs, against the measured no-Swing control
  (floor $49,414 / 2025 $12,377 / 2026 $8,731). It is the smaller number, because the other
  sleeves earn slightly more when Swing is not competing for capacity.

**When someone asks "what does Swing add?", the marginal column is the answer.** The 2026 figure
is negative on both, and worse on the one that matters.

## C. Current paper scope decision

| sleeve | in scope | basis |
|---|---|---|
| `global_nkd` | yes | route design |
| `roska4_stress` | yes | route design |
| `roska4_calm` | yes | route design |
| `roska4_swing` | yes | **operator override** — `D1_OLD_EFFECTIVE_EMA50`, `causal_d1` |

Signed `kevindo290`, 2026-08-29, in `track1_swing_paper_override.json`, sourced from Stage 5ZZZ-N.

```text
parameter_promotion   false          WFO parameters retained, nothing promoted
evidence_promotion    false
risk_acceptance       true
grants_orders         false
satisfies_shadow_evidence  false
```

Accepted **against** four recorded caveats, which stay attached to the decision:

1. same-day Swing not live-tradable
2. Swing 2026 contribution negative
3. no-Swing risk-adjusted OOS better
4. no bootstrap yet

**`PAPER_SHADOW_EVIDENCE` is still required and still blocking. No order activation.**

## D. Canonical sources — quote these

| file | holds |
|---|---|
| `scratch/track1_stage5zzzn_canonical_strategy_baseline_reproduction_20260829.json` | §A and §B, all 36 headline numbers, reproduced from code |
| `scratch/track1_stage5zzzn_canonical_strategy_baseline_reproduction_20260829.md` | the same, in prose |
| `track1_swing_paper_override.json` | §C, the signed scope decision |
| `track1_go_live_confirmation.json` | legacy retirement only — **carries no order-approval field** |
| this index | the reconciliation of all of the above |

## E. What not to quote, and why

| class | count | why not |
|---|---:|---|
| `REFERENCE_ONLY` | 24 | real numbers that are not attainable — chiefly the same-day Swing variant |
| `RESEARCH_ONLY` | 15 | parameter searches. **Nothing was promoted from any of them** |
| `REJECTED_RESEARCH` | 12 | SPY and ES intraday regime proxies — measured, not selected |
| `SUPPORTING_PROOF` | 381 | stage narratives, trade artifacts, param sidecars. Proof for one step, not a baseline |
| `TEST_ARTIFACT` | 109 | test suites |
| `DECISION_RECORD` | 15 | decisions, not measurements |
| `CANONICAL` | 2 | §D |

Named specifically:

- **Stage 5ZZZ-H** (`track1_stage5zzzh_full_candidate_swing_d1_remeasure_20260829.md`) —
  `REFERENCE_ONLY`. Carries the same-day column next to the D-1 one; quoting the wrong column is
  the easiest mistake in this repo.
- **Stage 5ZZZ-I** (`..._swing_d1_wfo_retune_...`) — `RESEARCH_ONLY`. A narrow D-1 retune to
  ema=10. Not promoted.
- **Stage 5ZZZ-L** (`..._swing_full_wfo_causal_d1_...`) — `RESEARCH_ONLY`, and its apparatus
  concern is **superseded by Stage 5ZZZ-M**, which found the real cause was an unrecorded
  ema 30→50 substitution in the regeneration wrapper.
- **Stage 5ZZZ-J / 5ZZZ-K** (SPY proxy, ES proxy) — `REJECTED_RESEARCH`.
- **Stage 5ZZZ-M** — `SUPPORTING_PROOF`. It explains *why* the selected identity is called
  "old/effective ema=50". It is not itself a baseline.
- **Pre-B1 blocker lists and stale slot-count docs** — `SUPERSEDED`. B1 was signed 2026-08-27 and
  the Track 1 slot table is **71**, not 70. Suites written before 08-27 still assert the older
  values and fail for that reason; they are known-stale, not regressions.

## F. Route state at compile time

```text
orders_possible          False
blocking                 ['PAPER_SHADOW_EVIDENCE']
orders dir               ABSENT
TRACK1_ORDERS_APPROVED   unset
confirmation             present, grants no order authority
swing paper override     present, valid, grants nothing
live Swing regime basis  causal D-1  (Stage 5ZZZ-Q)
```

**Remaining blocker before paper: `PAPER_SHADOW_EVIDENCE`.** It needs five judgeable days with
zero failures and complete Calm decision evidence. Every day currently in the qualifying window
was recorded *before* the Stage 5ZZZ-Q Swing fix, so the window cannot become entirely post-fix
until five post-fix trading days have run.
