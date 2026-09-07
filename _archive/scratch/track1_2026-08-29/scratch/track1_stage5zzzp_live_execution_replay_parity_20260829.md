# Stage 5ZZZ-P — live execution versus replay: a parity proof

**Route:** `track1_candidate` · **Date:** 2026-08-29 · Read-only · **Orders:** never enabled, still impossible

## Verdict

# All four sleeves: `NOT_YET_OBSERVED`

**No live slot has run since the fixes this parity is about.** The newest live slot ran at **2026-08-28T12:46:22**; the newest relevant fix landed at **2026-08-29T00:35:14** — five and a half hours later, and today is a Saturday with no session.

That is not a soft pass and it is not a failure. It is the answer, and the tool refuses to give any other one until a session runs.

| Sleeve | Verdict | Newest live slot | |
|---|---|---|---|
| `global_nkd` | **NOT_YET_OBSERVED** | `TRACK1_NKD_0255`, 2026-08-28 | ran before the fixes |
| `roska4_stress` | **NOT_YET_OBSERVED** | `TRACK1_STRESS_1230`, 2026-08-28 | ran before the fixes |
| `roska4_calm` | **NOT_YET_OBSERVED** | `TRACK1_CALM_OBSERVE_1002`, 2026-08-28 | ran before the fixes |
| `roska4_swing` | **NOT_YET_OBSERVED** | `TRACK1_SWING_1445`, 2026-08-28 | ran before the fixes |

`PASS: 0 · FAIL: 0 · UNKNOWN: 0 · NOT_YET_OBSERVED: 4`

**This counts toward `PAPER_SHADOW_EVIDENCE`: no.** Nothing here was wired as a gate, and the tool reports `counts_toward_paper_shadow_evidence: false` as a field.

---

## 1. How the cutoff was established

```text
2026-08-28T18:11   global_index/track1_normal_r4.py          observer seam
2026-08-28T18:31   global_index/run_live_day_track1.py       diagnostics persistence
2026-08-29T00:33   global_index/track1_strategy_diagnostics.py  regime-basis recording
2026-08-29T00:35   global_index/track1_live_source.py        basis passed at the call sites
                   -----------------------------------------------------------------
cutoff             2026-08-29T00:35:14
newest live slot   2026-08-28T12:46:22   (track1_signals_20260828.jsonl)
```

A corroborating fact rather than an inference: **`global_index/track1_runtime/strategy_diagnostics/` does not exist.** The runtime diagnostics store that Stage 5ZZZ-B wired has never been written, which is only possible if no slot has run since.

## 2. The replay harness

`global_index/track1_replay_parity.py` — read-only, no writes, no broker, no gate.

It reuses the market view's reconstruction rather than writing a second one. Stages 5ZZZ-B and 5ZZZ-G established that reconstruction mirrors the live call sites exactly — same parameters, same labels object, same detector. A parity check whose two sides come from two implementations is comparing the implementations, not the route.

```text
live side     global_index/track1_runtime/signals/track1_signals_YYYYMMDD.jsonl
              global_index/track1_runtime/shadow_intent/  (Calm phases)
replay side   track1_market_view._strategy(root, sleeve, day, spec)      NKD · Swing · Stress
              track1_strategy_diagnostics.calm_blocks(root, day)         Calm DECIDE/OBSERVE
entry point   track1_replay_parity.parity(root)
```

Verdicts: `PASS` every comparable field matched · `FAIL` a comparable field disagreed · `UNKNOWN` evidence missing or context unreconstructable · `NOT_YET_OBSERVED` no post-fix slot. **A partial match is `UNKNOWN`, never `PASS`.**

---

## 3. What the pre-fix slots showed — informational only

Run against 2026-08-28 anyway, so the harness is proven to work and so the evidence gaps are visible now rather than after the next session. **None of this counts.**

| Sleeve | Informational | Notable |
|---|---|---|
| `global_nkd` | UNKNOWN | route, sleeve, session date, data identity all matched; `params_hash` and `regime_basis` not recorded live |
| `roska4_stress` | UNKNOWN | route, sleeve, session date matched; data identity not exposed by the replay path; `params_hash` empty |
| `roska4_calm` | UNKNOWN | matched, **and both phase-isolation checks PASS** — DECIDE carries no OBSERVE-only value and no price level |
| `roska4_swing` | **FAIL** | see below |

### The Swing result is the finding of this stage

```text
swing_regime_basis_is_causal_d1     FAIL
  declared paper identity  causal D-1        (Stage 5ZZZ-O record, selected_identity D1_OLD_EFFECTIVE_EMA50)
  detector actually reads  "this session's own label"
```

Stage 5ZZZ-O recorded Swing's paper identity as `regime_basis: causal_d1`. Stage 5ZZZ-G measured that the live Swing detector is handed the raw label map and looks up **the session's own row**. Both remain true, and this parity check is the first place they are compared against each other rather than discussed separately.

**The distinction that matters:** the *artifact and backtest* identity is genuinely causal D-1 — Stage 5ZZZ-N proved it on 147 of 147 label-change sessions. The *live detector path* is not. The paper identity and the live path disagree, and the record signed in 5ZZZ-O describes the former.

This does not change any number in 5ZZZ-N, and it does not make the override invalid — but an operator reading "causal D-1" in the decision trail should know the live detector does not yet read that way. It is the same open finding Stage 5ZZZ-G declined to fix because it touches a runtime trading file; it now has a check that will keep saying so.

### Three evidence gaps, all reported as gaps

1. **`params_hash` is empty on every live row inspected.** No slot can reach `PASS` on that field until the live writer records it.
2. **The live row has no regime-basis field.** So NKD and Swing — the two sleeves whose identity turns on it — **cannot reach `PASS` at all today**, even with every other field agreeing. Pinned by its own test so it is not mistaken for a passing sleeve.
3. **Data identity is spelled two ways.** Live records `global_index/data/NKD_continuous_1m_8y.parquet`; the reconstruction records `NKD_continuous_1m_8y.parquet`. Same file. The comparison was changed to match on the file name, because a false `FAIL` is worse than an honest `UNKNOWN` — someone acts on it. The inconsistency is reported here rather than hidden by that fix.

---

## 4. Tests

`scratch/test_track1_stage5zzzp_replay_parity_20260829.py` — **19 passed**.

Covering: a fully matching slot passes (so `PASS` is reachable at all); params-hash mismatch fails; a *missing* hash is `UNKNOWN`; data-identity mismatch fails; the same file spelled two ways does not; an unreconstructable context is `UNKNOWN`; **a partial match is `UNKNOWN`, not `PASS`**; a slot older than the fixes is `NOT_YET_OBSERVED`; Swing on the session's own label **fails** and on a lagged basis passes; a Calm OBSERVE value or price level in DECIDE fails and a clean DECIDE passes; NKD/Swing cannot reach `PASS` until the basis is recorded; the module has no write path and no broker or order reference; it never claims to satisfy shadow evidence; the gates do not import it; and the real run reports no post-fix slot for any sleeve.

---

## 5. Answers

- **Slots checked:** the newest live slot for each of the four sleeves, all from 2026-08-28 — `TRACK1_NKD_0255`, `TRACK1_STRESS_1230`, `TRACK1_CALM_OBSERVE_1002`, `TRACK1_SWING_1445`.
- **Passed / failed / unknown / not yet observed:** `0 / 0 / 0 / 4`. Every sleeve is `NOT_YET_OBSERVED`.
- **Does live execution match replay?** **Not yet established.** No post-fix session has run. On the pre-fix slots the comparable fields agree for NKD, Stress and Calm, and Swing's regime basis disagrees with its declared paper identity.
- **Is evidence missing?** Yes, three ways: no `params_hash` on any live row; no regime-basis field on any live row; and the runtime diagnostics store has never been written.
- **Should any of this count toward `PAPER_SHADOW_EVIDENCE`?** **No.** Nothing was wired as a gate; the tool declares `counts_toward_paper_shadow_evidence: false`; and a `NOT_YET_OBSERVED` result is the opposite of evidence.

### What would make this answerable

One Track 1 session after 2026-08-29T00:35. That is Monday. The two evidence gaps — the params hash and the regime basis on the live row — need the live writer to record them, and neither is fixable from the reading side.

## 6. Safety

```text
orders_possible          False
blockers                 ['PAPER_SHADOW_EVIDENCE']
confirmation             present, approves no orders
swing paper override     present, valid, grants nothing
orders dir               ABSENT
TRACK1_ORDERS_APPROVED   unset
broker calls             ZERO
scheduler                pid 3000, track1-only-shadow, NOT restarted
backend                  pid 10136, NOT restarted
runtime trading files    untouched · strategy logic untouched · params untouched · gates untouched
runtime evidence         read only; nothing written, nothing marked satisfied
```
