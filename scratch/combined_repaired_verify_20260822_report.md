# Independent Verification of the Repaired Combined Replay — 2026-08-22

Scratch-only. Nothing in production was read for modification or changed.

The repaired replay reports its own `double_booked = 0`. A counter a script keeps about itself
is not evidence, so this rebuilds the same control flow with separate instrumentation and asks
questions the repaired script does not ask itself.

## The gate

The mirror must reproduce the repaired script's net, worst drawdown, and cashflow-ledger sum to
the cent, for every window and every policy. Anything else and the measurements below are not on
the same book.

**15 of 15 rows pass.** Net, drawdown and ledger sum agree exactly in all three windows across
all five policies.

Two further corroborations:

- Re-running the repaired script from scratch produces a **byte-identical** JSON (sha256
  `703d6ea2…`, file mtime moved 04:35 → 04:42). It is deterministic.
- Its internal accounting closes: `attempted = taken + rejected + suppressed + halted` holds
  exactly for Normal-R4 (752 / 105 / 81) and Calm A (349 / 44 / 28) in all fifteen rows.

## What the repairs actually did

### Double settlement — repaired, verified

Independent settlement audit, counting every position that entered the book against every
cashflow booked against it:

| | floor | 2025 | 2026 |
|---|---:|---:|---:|
| positions entered (independent caps) | 1,695 | 217 | 137 |
| positions settled | 1,695 | 217 | 137 |
| settled more than once | **0** | 0 | 0 |
| entered but never settled | **0** | 0 | 0 |
| settlements with no matching entry | 0 | 0 | 0 |

Identical result for all five policies. The −$635 of duplicated cashflows on the floor window is
gone, and nothing has gone missing in the other direction either.

One thing to say out loud, because the docs currently describe it as a skip: **the repair chose
"Stress closes the Calm A position", not "Stress leaves it alone".** Four Calm A positions per
floor window are force-closed at the Stress entry price. That is an order sent to the market, not
an omission, and the broker audit needs to know it exists.

### Same-symbol overlap — repaired, verified

Every instant where the book held two positions on the same contract:

**Zero, in all three windows, under all five policies.** Previously 10 / 1 / 1.

The suppression is now also counted, which it was not before: floor rises from 7 suppressed
Normal entries to 17, and their P&L is carried in the state.

### NKD price basis — repaired as a stopgap, verified

The repaired switch value matches the independent correction run to the dollar:

| Window | repaired script | independent correction |
|---|---:|---:|
| floor | +$1,790.00 | +$1,790.00 |
| 2025 | −$5.00 | −$5.00 |
| 2026 | −$3,172.50 | −$3,172.50 |

I also re-derived the offset from the parquet files **as they stand today**, rather than trusting
the literal written into the script: floor +100.0, 2025 −10.0, 2026 0.0, each a single value
across every overlapping bar, all three matching the hardcoded constants exactly.

That is correct today and fragile tomorrow. The offsets are written into the script as a literal
dictionary. Rebuild or re-roll either NKD parquet and the literal keeps its old value while the
data moves underneath it, silently. Derive it at run time, or better, do the real fix — regenerate
Calm-NKD from the same file the current-NKD artifact uses — which is already the plan for the
outstanding blocker.

### Family cap — added, and now sized properly

This one corrects my own earlier framing. I wrote that two 5% budgets on the same contracts "add
to 10% with nothing checking the sum". Structurally true; empirically the sum never got near 10%.

Combined Normal + Calm gross exposure, measured continuously at every event instant, not only at
entries:

| Window | no family cap: peak gross | peak net | with 5.0%/4.4% cap: peak gross | peak net | cost in net |
|---|---:|---:|---:|---:|---:|
| floor | **6.86%** | 6.86% | 4.90% | 4.89% | −$878 |
| 2025 | **7.82%** | 6.08% | 4.96% | 4.38% | −$116 |
| 2026 | **7.53%** | 7.53% | 4.84% | 4.12% | −$491 |

Median combined exposure is only 1.2–2.1% of account, and the ninetieth percentile 3.7–3.9%. So
the concern was a tail, not a norm — but the tail is real: 7.82% is **56% above** the 5% ceiling
the Normal cluster alone is held to, and nothing was checking it. The cap costs roughly 1.2% of
floor net to remove that tail.

**The cap is an admission gate, not a maintained limit.** No family entry was ever admitted above
its cap — the admission-time net peak on floor is exactly 4.40% against a 4.4% cap. But realised
net drifted to 4.89% on **7 occasions** in the floor window, attributed: 5 immediately after a
family position exited (dropping a short from a long-heavy book raises the net), and 2 observed at
an unrelated admission on a state that had already drifted. Zero breaches in 2025 and 2026.

This is not a flaw the family cap introduced — every cluster cap in the guard works the same way,
including the pre-existing 4.4% net cap on Normal alone. It is worth stating once so nobody reads
"4.4% net cap" as a guarantee about carried exposure. Peak overshoot measured: **+0.49 percentage
points, 11% over the cap.**

**The 7.5%/7.5% setting is a no-op on the floor window.** Zero family rejections, and every
column — net, PF, Sharpe, Calmar, drawdown, trades taken and rejected — is identical to running
with no family cap at all, with the peak still at 6.86%. On 2026 it looks better than the tighter
cap only because it happened to reject three legs that lost; 2026 is a sanity window and nothing
should be selected on it. **5.0%/4.4% is the only setting that constrains the tail in all three
windows.**

### The silent-drop path — not repaired, and never fired

If the forced-close price lookup returns nothing, the position is still removed from the book with
no cashflow booked. Measured occurrences across all fifteen runs: **zero**. It has never fired.
It is also more reachable than before, because the Stress branch now removes Calm A positions as
well as Normal ones. It should raise or count, not vanish.

## Repair status

| # | Item | Status |
|---|---|---|
| 1 | Stress double-settles a same-symbol Calm A position | **Repaired, independently verified** — 0 double settlements, 0 lost settlements |
| 2 | Normal-R4 opens into an existing Calm A | **Repaired, independently verified** — 0 same-symbol overlaps in 15/15 runs |
| 3 | Calm-NKD switch priced across two NKD series | **Repaired as a stopgap, verified** — matches to the dollar; offset literal re-derived and still correct, but will go stale silently |
| 4 | Calm-NKD declared risk ≈ 40× its true stop risk | **Not repaired** — acknowledged; blocks the full stack |
| 5 | Normal and Calm capped independently on shared contracts | **Repaired and sized** — untapped peak was 6.86–7.82%, not the 10% I implied; 5.0%/4.4% cap holds it to 4.84–4.96% |
| 6 | Max-hold exit pre-empts the armed stop | **Not repaired** — engine level, −$424 on floor, conservative direction |
| 7 | Forced-close price lookup drops a position silently | **Not repaired** — 0 occurrences, still fail-open |
| 8 | Normal suppression by Stress was uncounted | **Repaired** — now counted with its P&L |
| 9 | Production arms at 14:00, artifacts assume 14:05 | **Not repaired** — needs artifact regeneration |
| 10 | Swing entries stamped at the start of the 5-minute bar, filled at its close | **Not repaired** — latent, no effect on current sleeves |
| 11 | Two Calm A legs on a session the artifact clip excludes | **Not repaired** |

## Verdict on the repair

The mechanical blockers are genuinely fixed, and the fix is confirmed by instrumentation the
repaired script does not contain. The label "risk-clean fallback" is accurate **at the replay
level**; three items above (6, 9, 10) sit below the replay, in the engine and in the captured
artifacts, and are untouched by this repair. None of them is large — the measured cost of item 6
is $424 across seven years and it errs conservative — but "risk-clean" should carry the
qualifier rather than imply the whole chain has been cleared.

## Artifacts

- `scratch/combined_repaired_verify_20260822.py` / `.json` — the mirror, the gate, settlement and
  overlap audit
- `scratch/combined_family_exposure_probe_20260822.py` / `.json` — continuous family exposure and
  breach attribution
