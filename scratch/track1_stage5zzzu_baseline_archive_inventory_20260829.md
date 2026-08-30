# Stage 5ZZZ-U — the archive inventory, and one number the brief had mislabelled

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

**558 files inventoried. Nothing deleted, moved or renamed. No historical report rewritten.**

---

## 1. I checked the brief's numbers before publishing them

The brief hands over the figures to put in the canonical index. That is a hand-off, not a source,
and this index is precisely the file that future work will quote without re-deriving. So all
**36 headline numbers were compared field by field** against the Stage 5ZZZ-N artifact on disk.

**All 36 match.** Every net, PF, Sharpe, Calmar and MaxDD in §A and §B is what the artifact
records.

### One thing did not match: a label, not a number

The brief calls `+18,429 / +3,906 / −464` the **"Swing contribution"**. Those values are correct,
but they are the Swing **cluster P&L** — `pnl_by_cluster.roska4_swing`, an accounting split of the
full stack. They are not what Swing *adds*.

Measured against the no-Swing control that already exists in the same artifact:

| window | cluster P&L | no-Swing control | **marginal** |
|---|---:|---:|---:|
| floor | +$18,429 | $49,414 | **+$17,382** |
| 2025 | +$3,906 | $12,377 | **+$3,804** |
| 2026 | −$464 | $8,731 | **−$626** |

The gap is about **$1,000 on the floor**, because the other three sleeves earn slightly more when
Swing is not competing with them for capacity. And on 2026 — the window the operator's risk
acceptance is most exposed to — the marginal figure is **worse** than the cluster figure:
**−$626 against −$464**.

Both are true. They answer different questions, and "what does Swing add?" is answered by the
marginal column. **The index publishes both, labelled, side by side**, because publishing only one
is how the two get confused.

*Arithmetic self-check:* the four cluster P&Ls sum exactly to the full-stack net in all three
windows, which is what makes the cluster split an identity rather than an estimate.

## 2. What was inventoried

| class | count | meaning |
|---|---:|---|
| `SUPPORTING_PROOF` | 381 | stage narratives, trade artifacts, param sidecars — proof for one step |
| `TEST_ARTIFACT` | 109 | test suites |
| `REFERENCE_ONLY` | 24 | real numbers that are not attainable |
| `DECISION_RECORD` | 15 | decisions, not measurements |
| `RESEARCH_ONLY` | 15 | parameter searches; **nothing promoted from any of them** |
| `REJECTED_RESEARCH` | 12 | SPY and ES regime proxies |
| `CANONICAL` | 2 | the Stage 5ZZZ-N reproduction, in both forms |

Patterns searched: `docs/futures/*`, `scratch/track1_stage*`, and the `*baseline*`, `*handoff*`,
`*wfo*`, `*proxy*`, `*canonical*`, `*decision*` families, plus the test suites, the
`normal_promotion_trades_*` artifacts and the `*.params.json` sidecars.

**An index rather than an edit.** No old report was rewritten. Each stays readable as it was
written, and the index carries the judgement about how to read it.

### A guard on my own classification

My first pass hand-curated ten high-risk files by path — and **four of those paths did not
exist**, because I had guessed the filenames. The curation was silently doing nothing for them.
The script now refuses to run if any curated path is missing, which is the only reason the error
surfaced instead of shipping.

## 3. The files most likely to be misquoted

| file | status | why not quote it |
|---|---|---|
| Stage 5ZZZ-H remeasure | `REFERENCE_ONLY` | carries the same-day column beside the D-1 one — the easiest wrong column in the repo |
| Stage 5ZZZ-I retune | `RESEARCH_ONLY` | a narrow D-1 retune to ema=10, **not promoted** |
| Stage 5ZZZ-L full grid | `RESEARCH_ONLY` | winner not promoted; its apparatus concern is **superseded by 5ZZZ-M** |
| Stage 5ZZZ-J SPY proxy | `REJECTED_RESEARCH` | measured, not selected |
| Stage 5ZZZ-K ES proxy | `REJECTED_RESEARCH` | a label-recovery test, not a trading backtest |
| Stage 5ZZZ-M obedience | `SUPPORTING_PROOF` | explains *why* the identity is "old/effective ema=50"; not a baseline |

**Superseded classes:** pre-B1 blocker lists (B1 signed 2026-08-27), stale slot-count documents
(the table is **71**, not 70), old dashboard wording docs (5ZZZ-F and 5ZZZ-S changed the
contract), and Stage 5ZZZ-L's apparatus concern.

## 4. Final Track 1 baseline summary

**Reference only — includes same-day Swing, which is not live-tradable:**
full stack **+$74,410 / +$16,997 / +$9,288**; risk-clean **+$64,903 / +$13,236 / +$8,260**.

**Selected paper baseline — causal D-1 old/effective ema=50:**
full stack **+$66,796 / +$16,181 / +$8,105**; risk-clean **+$57,289 / +$12,419 / +$7,077**.

Paper scope: NKD, Stress and Calm by route design; **Swing by operator override**, signed
`kevindo290` on 2026-08-29, `parameter_promotion: false`, `evidence_promotion: false`, WFO
parameters retained, and four caveats attached to the decision rather than filed away.

## 5. Validation

`scratch/test_track1_stage5zzzu_baseline_index_20260829.py` — the numbers are checked **against
the artifact rather than pinned as literals**, so the index cannot quietly drift from what it
describes. It also asserts the absences: the index may never say same-day Swing is tradable, and
may never claim orders are possible. And it checks that every file the index points at actually
exists — the failure mode I hit in §2.

---

## 6. Remaining blocker before paper

**`PAPER_SHADOW_EVIDENCE`.** It needs five judgeable days with zero failures and complete Calm
decision evidence. Every day currently in the qualifying window was recorded **before** the Stage
5ZZZ-Q Swing fix, so the window cannot become entirely post-fix until five post-fix trading days
have run. The first post-fix Swing slot is **Monday 2026-08-31, 14:05 ET**.

### Safety

```text
orders_possible          False
blockers                 ['PAPER_SHADOW_EVIDENCE']
orders dir               ABSENT
TRACK1_ORDERS_APPROVED   unset
confirmation             present, untouched, grants no order authority
swing paper override     present, valid, grants nothing
broker calls             ZERO
scheduler / backend      NEITHER restarted
files deleted/moved/renamed                    NONE
runtime trading files touched                  NONE
strategy logic · params · gates                unchanged
```
