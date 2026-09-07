# Stage 5ZZZ-N — canonical Track 1 baselines, reproduction proof, and the paper decision

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Commit:** `601970bf97e23b200b8eb06cbcf22a240897133a` · branch `future/incorporation`

## Final labels

```text
TRACK1_REFERENCE_BASELINE_REPRODUCED
LIVE_TRADABLE_BASELINE_REPRODUCED
INCLUDE_SWING_IN_PAPER_BY_OPERATOR_OVERRIDE
NO_SWING_PARAMETER_PROMOTION
PAPER_NOT_READY
NO_ORDER_ACTIVATION
```

> **Swing is included in paper scope by explicit operator risk acceptance, using causal D-1 old/effective ema=50. This is not an evidence-based parameter promotion. Same-day Swing remains reference-only and not live-tradable.**

---

## Part A — Historical reference baseline: reproduced, 30/30

Re-run from the producing script this stage, not copied from a prior report.

```text
command   python scratch/track1_stage5zzzh_full_replay_20260829.py --variant base
reads     scratch/normal_promotion_trades_{floor,vault2025,vault2026}_20260821.json
mode      REPLAYED from existing artifacts (no regeneration)
```

| Window | Policy | Net | PF | Sharpe | Calmar | MaxDD | vs doc |
|---|---|---:|---:|---:|---:|---:|---|
| floor 2018-2024 **(in-sample)** | full stack, cap 5.0/4.4 | +$74,410 | 1.67 | 2.12 | 2.14 | $4,973 | **MATCH** |
| 2025 **(OOS)** | full stack | +$16,997 | 2.26 | 2.76 | 4.45 | $3,901 | **MATCH** |
| 2026 to 08-19 **(OOS, partial)** | full stack | +$9,288 | 1.62 | 2.47 | 3.41 | $4,342 | **MATCH** |
| floor **(in-sample)** | risk-clean | +$64,903 | 1.62 | 2.34 | 1.92 | $4,845 | **MATCH** |
| 2025 **(OOS)** | risk-clean | +$13,236 | 2.00 | 2.96 | 3.09 | $4,632 | **MATCH** |
| 2026 **(OOS, partial)** | risk-clean | +$8,260 | 1.55 | 2.57 | 2.75 | $4,797 | **MATCH** |

**These are the SAME-DAY reference numbers. They are not the D-1 numbers and must never be quoted as the paper baseline** — the same-day regime label is computed from the session's 16:00 close and cannot exist during the 14:05–15:55 Swing window.

---

## Part B — Live-tradable selected baseline: reproduced from code

Regenerated, not replayed — the artifact was rebuilt from the engine and then replayed.

```text
regenerate  python scratch/track1_stage5zzzh_swing_d1_regen_20260829.py \
                --which floor vault2025 vault2026 --suffix d1repro
replay      python scratch/track1_stage5zzzh_full_replay_20260829.py --variant d1repro
elapsed     765.6s regeneration
```

### Reproduced artifacts match the D-1 arm byte for byte

| Window | d1repro sha256 (16) | existing d1 | |
|---|---|---|---|
| floor | `2474723814ae3e92` | `2474723814ae3e92` | **identical** |
| vault2025 | `c27ca3902b116912` | `c27ca3902b116912` | **identical** |
| vault2026 | `1ee198a9f10387c8` | `1ee198a9f10387c8` | **identical** |

### Effective parameters — requested differ from effective, and both are recorded

Every window's sidecar (`*.params.json`), written by the regeneration:

```text
asked_ema_period            30
effective_ema_period        50          <- SUBSTITUTED
ema_was_substituted         true
effective_stop_basis_atr_mult  2.0
ratchet                     false
chandelier_affects_decisions  false
labels                      RegimeLabels(lag_days=1) causal D-1
```

The substitution is `scratch/harness.py`'s deliberate rule (`ema_period == 30 → cfg.ema = 50`), characterised in Stage 5ZZZ-M. **Requested ≠ effective, and this is the first stage where both are on record.**

### Regime basis — causal D-1, proven on disagreeing sessions

The regeneration's own probe landed on a session where the same-day and previous-day labels agree, which proves nothing. A separate proof takes every session in the floor window where they **disagree**:

```text
label-change sessions:                                    147
object returned the PREVIOUS session's label on:      147/147
mismatches:                                                 0

2018-02-02   same-day=Normal   previous=Calm     object=Calm
2018-02-06   same-day=Stress   previous=Normal   object=Normal
2018-02-16   same-day=Normal   previous=Stress   object=Stress
```

**No same-day label, no proxy label, no retuned params, no prevbar.**

### The reproduced numbers

| Window | Full stack | expected | Risk-clean | expected | Swing $ | expected |
|---|---:|---:|---:|---:|---:|---:|
| floor **(in-sample)** | **+$66,796** | +$66,796 ✓ | **+$57,289** | +$57,289 ✓ | **+$18,429** | +$18,429 ✓ |
| 2025 **(OOS)** | **+$16,181** | +$16,181 ✓ | **+$12,419** | +$12,419 ✓ | **+$3,906** | +$3,906 ✓ |
| 2026 **(OOS, partial)** | **+$8,105** | +$8,105 ✓ | **+$7,077** | +$7,077 ✓ | **−$464** | −$464 ✓ |

Full metrics, full stack: floor PF 1.59 / Sharpe 1.91 / Calmar 1.92 / MaxDD $4,973 · 2025 PF 2.05 / 2.50 / 3.36 / $4,915 · 2026 PF 1.52 / 2.14 / 3.76 / $3,435. Swing taken/rejected 564/197 · 57/48 · 43/38.

Sleeve split (full stack): floor Swing $18,429 · Stress $26,166 · Calm $8,797 · NKD $13,405. 2025: $3,906 / $4,531 / $1,780 / $5,964. 2026: −$464 / $831 / $702 / $7,036.

### Integrity

```text
baseline artifact sha256 BEFORE and AFTER — unchanged
  floor      f4d8eea7cd051b3d84a828f15382749097a17cc4c40168b3f045c6ad8a41c588
  vault2025  c7eb5dd2e375316b4edef32a42c2d8b36546c2971e6ff3eb3e083d23e8c86d27
  vault2026  b1e85b2c9ab7019dce54d37a70bbb3b7248078f63a71d2eec7a5321124f8991b
```

The regeneration writes to the shared baseline filenames and restores them from a backup in a `finally`; it reported `baselines restored byte-identical: YES` and the hashes above confirm it independently. **No baseline artifact was modified.**

---

## Part C — Every variant measured, in one table

Net figures are **full stack / risk-clean**. `n/m` = not measured. floor is **in-sample**; 2025 and 2026 are **out-of-sample**; 2026 runs only to **2026-08-19 (partial)**.

| # | Variant | Regime basis | Requested | Effective | Live-tradable | Paper | floor net | 2025 net | 2026 net | Swing floor/2025/2026 | Decision | Caveat |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Historical same-day reference** | same-day daily close | ema 30 | **ema 50** | **NO** | no | $74,410 / $64,903 | $16,997 / $13,236 | $9,288 / $8,260 | +25,677 / +4,690 / +719 | reference only | label needs the 16:00 close; cannot exist at 14:05 |
| 2 | **D-1 old / effective ema=50** | **causal D-1** | ema 30, mult 2.5 | **ema 50**, stop basis 2.0 | **YES** | **YES — operator override** | **$66,796 / $57,289** | **$16,181 / $12,419** | **$8,105 / $7,077** | **+18,429 / +3,906 / −464** | **SELECTED** | Swing negative in 2026; not an evidence promotion |
| 3 | D-1 narrow retune (Stage I) | causal D-1 | ema 10, mult 2.5 | ema 10 | yes | no | $64,374 / $54,867 | $10,040 / $6,279 | $6,946 / $5,918 | +16,883 / −2,190 / −1,623 | **rejected** | worse OOS in both windows; tuned on the research engine |
| 4 | D-1 full-grid winner (Stage L) | causal D-1 | ema 50, mult 2.0 | **ema 50** — *identical to #2* | yes | via #2 | = #2 | = #2 | = #2 | = #2 | **converged onto #2** | mult is a no-op (ratchet off, stop basis set) |
| 5 | D-1 prevbar vol filter | causal D-1 | ema 30 → 50, `rvol_prevbar` | ema 50 | yes | no | $64,477 / $54,970 | **$17,758** / $13,996 | $6,918 / $5,889 | +16,225 / **+5,483** / −1,652 | **not promoted** | best 2025 of any arm; weak 2026, worse drawdown |
| 6 | SPY intraday proxy | pre-14:00 SPY proxy | n/a | n/a | yes (causal) | no | $45,603 / $36,096 | **n/m** | **n/m** | −2,433 / n/m / n/m | **rejected** | SPY intraday ends 2024-12-30; no OOS possible; below no-Swing in-sample |
| 7 | ES intraday proxy | pre-14:00 ES proxy | n/a | n/a | yes (causal) | no | **n/m** | **n/m** | **n/m** | n/m | **rejected** | label-recovery only: 81.9% vs D-1's 91.5% on floor; −5.2 / −11.4 pts OOS. No backtest run |
| 8 | **no-Swing control** | n/a | n/a | n/a | yes | no | $49,414 / $39,907 | $12,377 / $8,616 | **$8,731** / $7,703 | 0 / 0 / 0 | control | best risk-adjusted OOS of any arm (Calmar 8.05 / 8.92) |

Variants 6 and 7 were never run through the full stack for 2025/2026 — 6 because the data does not exist, 7 because it failed its label-recovery precondition. **Those cells are marked not measured, not zero.**

---

## Part D — Final decision

**Swing is included in paper scope by explicit operator risk acceptance, using causal D-1 old/effective ema=50. This is not an evidence-based parameter promotion. Same-day Swing remains reference-only and not live-tradable.**

- **D-1 old / effective ema=50 is selected** because it is the current effective route identity, and because the full-grid WFO — 48 candidates under causal D-1, on the engine that makes the artifacts — **converged back onto it**.
- **Retuned D-1 (ema=10) is rejected**: worse in both OOS windows, Swing negative in both.
- **SPY intraday proxy is rejected**: no 2025/2026 data at all, and below the no-Swing route in-sample.
- **ES intraday proxy is rejected**: loses to D-1 persistence in every window, including both OOS.
- **Prevbar is not promoted**: the strongest 2025 of any arm, but weak 2026 and a worse drawdown — one good window is not evidence.
- **WFO remains the validation framework** for any future Swing change.

### What the evidence does *not* say

Stage 5ZZZ-L's pre-committed thresholds, scored against the selected arm (which the WFO winner equals):

| | |
|---|---|
| T1 net ≥ D-1 old in ≥3 of 4 OOS cells | **PASS** (identical) |
| T2 Swing contribution ≥ $0 in **both** OOS windows | **FAIL** — 2026 −$464 |
| T3 Calmar ≥ no-Swing in ≥1 OOS, ≥60% in both | **FAIL** — 42% in both |
| T4 MaxDD ≤ 115% of D-1 old | **PASS** (identical) |
| T5 fold stability ≥ 50% | **PASS** — 5/10, five consecutive |

**Two of five fail.** The inclusion is an operator decision taken with that on the record, not a result the evidence produced.

---

## Part E — Paper scope matrix

| Sleeve | In paper scope | Live-tradable | Identity | Evidence |
|---|---|---|---|---|
| **NKD** (`global_nkd`) | yes | yes | `RegimeLabels(lag_days=1)`, ema 10, context filter off | **pending** |
| **Stress** (`roska4_stress`) | yes | yes | basket gate decided 10:30 ET | **pending** |
| **Calm** (`roska4_calm`) | yes | yes, two-phase | DECIDE 09:32 / OBSERVE 10:02, phases isolated | **pending** |
| **Swing** (`roska4_swing`) | yes — **operator override** | yes | **causal D-1, effective ema=50**, stop basis 2.0 | **pending** |

All four are in scope by decision. **No sleeve has paper evidence yet** — `PAPER_SHADOW_EVIDENCE` is still a blocker for the route as a whole.

---

## Part F — Gate and safety state, measured

```text
orders_possible          False
blockers                 ['B1_broker_account_or_legacy_retirement', 'PAPER_SHADOW_EVIDENCE']
confirmation file        present, confirmed_by 'kevindo290'
                         carries no order-approval key - it retires the legacy runner, nothing more
orders dir               ABSENT
TRACK1_ORDERS_APPROVED   unset
scheduler                pid 3000, mode track1-only-shadow, NOT restarted
backend                  pid 10136, NOT restarted
broker calls             ZERO - this stage needed none
runtime evidence         untouched
live route params        untouched; SWING_TF_PARAM unchanged
```

`B1` is present again because it reopens on the age of the account baseline record — the documented timer behaviour from Stage 5ZZZ-E, not anything this stage did. Account baseline freshness could not be read further without a broker call, and none was made.

**`PAPER_SHADOW_EVIDENCE` remains required. `orders_possible` remains false. No order was sent.**

---

## Part G — Validation

`scratch/test_track1_stage5zzzn_canonical_baseline_20260829.py` pins every claim above against the JSON deliverable, so this cannot go ambiguous again: the JSON parses; same-day is marked not live-tradable; the selected identity has effective ema 50 with requested 30 recorded beside it; reference and live-tradable baselines are separate sections; the risk-clean reference numbers are not labelled D-1; Swing inclusion is recorded as an operator override rather than a promotion; no parameter promotion is claimed; orders are never stated as possible; floor is marked in-sample, 2025/2026 OOS, 2026 partial; and every unmeasured cell is explicitly `not_measured` rather than filled.

---

## Answers

1. **All historical reference numbers reproduced** — 30/30, re-run this stage.
2. **D-1 old / effective ema=50 reproduced** — artifacts byte-identical, all 12 figures matched, effective ema 50 recorded, causal D-1 proven on 147/147 disagreeing sessions.
3. **Final paper baseline:** full stack $66,796 / $16,181 / $8,105 · risk-clean $57,289 / $12,419 / $7,077 · Swing +$18,429 / +$3,906 / −$464.
4. **Swing decision:** included by operator override on causal D-1 effective ema=50. **Caveat: not an evidence-based promotion — T2 and T3 fail, Swing is negative in 2026, and the no-Swing route is better risk-adjusted out-of-sample in both windows.**
5. **WFO does not need rerunning now.** The 48-candidate causal-D-1 search already converged on the selected identity, on the correct engine. It remains the framework for any future change.
6. **Before paper orders:** `PAPER_SHADOW_EVIDENCE` must be satisfied by real shadow sessions across all four sleeves, `B1` must close on a fresh account baseline record, and the operator's override must be recorded in the route's own decision trail rather than only in this report.
7. **Safety:** orders_possible **False** · blockers `['B1_broker_account_or_legacy_retirement', 'PAPER_SHADOW_EVIDENCE']` · confirmation present and approves no orders · orders dir absent · `TRACK1_ORDERS_APPROVED` unset · **zero broker calls** · scheduler pid 3000 and backend pid 10136 untouched.
