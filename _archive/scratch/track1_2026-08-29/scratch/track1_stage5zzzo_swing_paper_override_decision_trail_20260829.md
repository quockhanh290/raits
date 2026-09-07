# Stage 5ZZZ-O — the Swing paper override, moved into the route's decision trail

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

## What changed

The operator's decision now lives where the route can read it, and nowhere near a gate.

```text
new   track1_swing_paper_override.json                  the record
new   global_index/track1_swing_paper_override.py       a read-only reader that grants nothing
edit  global_index/track1_paper_readiness.py            renders it, ABOVE the legacy B1 block
```

No strategy logic, no Swing parameter, no WFO artifact, no gate, and no order path was touched.

---

## 1. The existing mechanism, and where this fits

The route already had a decision pattern worth following rather than inventing around:

| | |
|---|---|
| `track1_go_live_confirmation.json` | the signed B1 commitment — written by a person, never by a script |
| `global_index/track1_b1_decision.py` | a **read-only** preview module with no write path at all, asserted by test |
| `global_index/track1_paper_readiness.py` | the evidence half, and the operator-facing `report()` |
| `global_index/track1_gates.py` | `BLOCKERS`, `blocking()`, `may_enable_orders()` |

The new record follows `track1_b1_decision`'s contract exactly: a `SCHEMA` constant, strict validation, fail-closed, and **no code path that writes anything** — asserted by an AST walk over the module.

## 2. Measured before the module existed

The baseline that makes "grants nothing" a measurement rather than a claim:

```text
BEFORE any override record existed
  may_enable_orders                     -> False
  blocking                              -> ['PAPER_SHADOW_EVIDENCE']
  gates source mentions 'swing_override'-> False
  record file present                   -> False
```

## 3. The record

`track1_swing_paper_override.json`, every required field present:

```text
decision_type       swing_paper_scope
decision            INCLUDE_SWING_IN_PAPER_BY_OPERATOR_OVERRIDE
confirmed_by        kevindo290          confirmed_at  2026-08-29
route               track1_candidate    sleeve        roska4_swing
regime_basis        causal_d1           selected_identity  D1_OLD_EFFECTIVE_EMA50
parameter_promotion false               evidence_promotion false
risk_acceptance     true
source_stage        5ZZZ-N
baseline_reference  scratch/track1_stage5zzzn_canonical_strategy_baseline_reproduction_20260829.json
caveats             same-day Swing not live-tradable
                    Swing 2026 contribution negative
                    no-Swing risk-adjusted OOS better
                    no bootstrap yet
```

**The caveats are validated, not decorative.** A record that has dropped any of them is refused — an override whose reasons-against have gone missing reads as an endorsement, and this one must never be quotable without them.

## 4. It grants nothing, and that is measured three ways

```text
AFTER the record exists
  may_enable_orders -> False
  blocking          -> ['PAPER_SHADOW_EVIDENCE']        <- identical to before
```

- **The object says so.** `grants_orders`, `satisfies_shadow_evidence`, `is_parameter_promotion`, `is_evidence_promotion` are all `False` on every `Override`, valid or not.
- **The import graph says so.** A test asserts `track1_gates`'s source contains no reference to this module — matching what was measured before it was written.
- **The strongest form:** a test moves the record aside, re-asks `may_enable_orders()` and `blocking()`, restores it, and asserts the two answers are **identical**. If the gates moved, the record is not inert.

A valid record and a corrupt one grant exactly the same thing: nothing. The only difference is what the operator is told.

### Fail-closed on every axis

Refused, each with its own reason: absent · unreadable · not an object · any missing required field · wrong schema, decision, decision_type, route, sleeve, regime_basis or selected_identity · unsigned · empty timestamp · **claiming `parameter_promotion` or `evidence_promotion`** · `risk_acceptance` not true · any caveat dropped · expired (`expires_at` is optional; enforced when present).

## 5. What an operator sees

In `track1_paper_readiness.report()`, placed **above** the B1 block rather than after it — an operator's risk acceptance is not a footnote to the legacy decision:

```text
  READY FOR PAPER (evidence half): False

  SWING PAPER SCOPE : included by operator risk acceptance
         identity   D1_OLD_EFFECTIVE_EMA50  ·  regime basis causal_d1
         accepted   kevindo290 at 2026-08-29  (stage 5ZZZ-N)
         This is NOT a parameter promotion and NOT an evidence promotion.
         It releases no gate and does not satisfy PAPER_SHADOW_EVIDENCE.
         Accepted against:
           - same-day Swing not live-tradable
           - Swing 2026 contribution negative
           - no-Swing risk-adjusted OOS better
           - no bootstrap yet
         baseline   scratch/track1_stage5zzzn_canonical_…_20260829.json
```

The position is asserted by a test, not by intention: a mutation that moves it below the B1 block goes red.

## 6. Paper scope

`paper_scope()` reports all four sleeves in scope, with the basis on each and evidence pending on all:

| Sleeve | In scope | Basis | Evidence |
|---|---|---|---|
| `global_nkd` | yes | `in_scope_by_route_design` | pending |
| `roska4_stress` | yes | `in_scope_by_route_design` | pending |
| `roska4_calm` | yes | `in_scope_by_route_design` | pending |
| **`roska4_swing`** | yes | **`operator_override`**, `risk_accepted: true` | pending |

`evidence_promoted` and `parameter_promoted` are `false` on Swing. With the record removed, Swing stays in scope but the basis falls back to `in_scope_by_route_design` and `risk_accepted` becomes false — the sleeve does not vanish, and the override stops being claimed.

## 7. Validation

**64 tests pass** (43 new here, 21 from the canonical suite re-run). The new ones cover: the record parses only with every required field; each field individually removed grants nothing; absent/unreadable/unsigned/mismatched/expired grant nothing; a record claiming either promotion is refused; each caveat individually dropped is refused; the override never claims authority; the gates do not import it; **the gate answer is identical with the record present and absent**; it does not satisfy shadow evidence; it changes no parameter; the module has no write path; paper scope has four sleeves with Swing as an override; scope degrades correctly without the record; the record agrees with the canonical baseline on identity and regime basis; same-day Swing is still marked not live-tradable; and the report shows the override with every caveat, above the B1 block.

**Mutation harness: 10/10 red.** Allowing a promotion claim · tolerating a dropped caveat · accepting an unsigned record · claiming to grant orders · claiming to satisfy shadow evidence · ignoring a route/sleeve mismatch · honouring an expired record · reporting Swing as evidence-promoted · trimming the caveats out of the rendering · burying the block under B1.

**One honest note on the harness.** It reported `restored byte-identical: NO` for the new module. The cause was line endings, not content: the read/write round-trip converted the file from LF to CRLF, which is the convention the rest of the package already uses (`track1_paper_readiness.py` is likewise all-CRLF). Content verified unchanged — no mutation text survives, 224 lines, 4 definitions, 14 refusal paths, and all 64 tests pass. Recorded rather than quietly ignored, because a restore check that fires is only useful if its firing is explained.

---

## Answers

1. **The Swing override is now recorded outside the report** — `track1_swing_paper_override.json`, read by `global_index/track1_swing_paper_override.py` and rendered in the readiness report.
2. **All four sleeves are in paper scope**, with evidence pending on every one. Swing's basis is `operator_override`; the other three are in scope by route design.
3. **`orders_possible` remains False** — identical before and after the record, asserted by a test that removes it and re-asks.
4. **`PAPER_SHADOW_EVIDENCE` remains the blocker.** The override does not satisfy it and cannot.
5. **No params, gates or orders changed.** `SWING_TF_PARAM` unchanged; `track1_gates.py` untouched; no order path exists on this route regardless.
6. **Safety:** below.

## Safety state

```text
orders_possible          False
blockers                 ['PAPER_SHADOW_EVIDENCE']       (B1 closed again on baseline age)
confirmation             present, confirmed_by 'kevindo290', approves no orders
swing override           present, valid, grants nothing
orders dir               ABSENT
TRACK1_ORDERS_APPROVED   unset
scheduler                pid 3000, track1-only-shadow, NOT restarted
backend                  pid 10136, NOT restarted
broker calls             ZERO
runtime evidence         untouched · strategy logic untouched · WFO artifacts untouched
```
