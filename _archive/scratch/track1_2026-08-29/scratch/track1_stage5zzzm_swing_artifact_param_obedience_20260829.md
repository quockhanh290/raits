# Stage 5ZZZ-M — why the Swing artifact ignored ema=50

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

## Root cause

`scratch/harness.py`, inside the replacement engine the regeneration installs:

```python
apply_fixes = (not cfg.roska4_only) or (ema_period == 30)
if cfg.ema is not None and ema_period == 30:
    ema_period = cfg.ema                     # cfg.ema = 50
```

and `scratch/normal_promotion_regen_audit_20260821.py` builds that engine with

```python
cfg = Cfg(fix_fill=False, arm_hours=ARM_LIVE, ratchet=False,
          roska4_only=False, ema=50, stop_basis=2.0)
```

**A request for `ema_period=30` is rewritten to 50.** Every other value passes through untouched. So the "ema=30 default" artifact and the "ema=50" artifact are byte-identical because **they are the same run** — not because the parameter was ignored, and not because the two settings happen to coincide.

**The parameter was never disobeyed. Nothing recorded that it was translated.** That is the actual defect, and it is a reporting defect, not an engine one.

### Proven, not argued

Four regenerations of the same window, one per case, each recording what the engine received:

| case | asked | effective | artifact sha256 (16) | filtered counts (MES/MNQ/MYM/M2K) |
|---|---|---|---|---|
| A default | ema 30, mult 2.5 | **ema 50** | `1ee198a9f10387c8` | 21 / 18 / 23 / 19 |
| B WFO winner | ema 50, mult 2.0 | ema 50 | `1ee198a9f10387c8` | 21 / 18 / 23 / 19 |
| C | ema 10, mult 2.0 | ema 10 | `b878f9fd39cb7171` | 22 / 20 / 24 / 23 |
| D | ema 20, mult 2.0 | ema 20 | `ef3ef40d10f36315` | 22 / 19 / 24 / 23 |

A ≡ B exactly as the substitution rule predicts; C and D each distinct. A fifth run at ema 50 / mult **2.5** also lands on `1ee198a9f10387c8`, which settles the chandelier separately (below).

---

## The nine questions

**1. Does the override reach the public regeneration entry point?** **Yes.** The run records it at the call site: `engine actually received (ema, mult, hold): [(50, 2.0, 5)]`.

**2. Does it reach the artifact engine that writes the files?** **Yes** — and that engine is where the substitution happens. The chain is `SwingTFEngine.backtest` → `_validated_core.backtest_swing_tf`, which the regeneration has replaced with `patched_engine(cfg)`'s function.

**3. Does it reach the detector/signal function?** **Yes**, carrying the *substituted* value. `TrendFollowStrategy` is built with `c["ema_period"] = ema_period` after the rewrite, so the detector genuinely runs ema 50.

**4. Are ema=30 and ema=50 genuinely equivalent?** **No — they were never both run.** This is the question the previous stage could not answer and the reason it stalled. The two artifacts are one artifact.

**5. Is a cache involved, and is its key complete?** A cache exists — `_swing_cache`, keyed on `id(df)` alone — and it is **not** the cause. It holds the daily ATR, the day list, per-day OHLC arrays and per-day 5-minute frames: all price-derived, none parameter-derived. Its own docstring says it is keyed that way *"so WFO reuses across param/fold calls"*, i.e. param-independence is the design. **The key is complete for what it holds**, and that is asserted two ways — a source check that nothing ema/chandelier/hold-derived enters it, and a behavioural check that the same frame object at ema 10 and ema 50 still yields different trades.

**6. Does the artifact metadata record the effective params?** **It did not.** The artifact carries `argv`, `nkd_instrument` and `slippage_ticks` — the *request*, never the *result*. This is the gap that turned a documented translation into a stage-long mystery.

**7. Can the digest be made to change when a decision-affecting parameter changes?** **Yes for `ema_period`** — 10, 20 and 50 each produce a distinct artifact. **No for `chandelier_atr_mult`**, and that is correct rather than broken: with `ratchet=False` and `stop_basis=2.0` the day loop never recomputes the stop, so the multiple only reaches the strategy config. `NormalR4Params`' own docstring says so — *"`chandelier_atr_mult` is here and is NOT a stop width"* — and it is now measured: ema 50 at mult 2.0 and at mult 2.5 give the same artifact.

**8. Which numbers are provisional?** See below — the answer is narrower than the previous stage feared.

**9. What is the next safe measurement?** The `range_max` / `rel_volume_max` second pass, which Stage 5ZZZ-L planned and could not reach, now that a run records what it actually ran. Then a day-level bootstrap on the OOS windows.

---

## The fix

Additive only. The promotion artifacts are hash-pinned baselines and adding a key to them would break every reproduction that depends on them, so the effective parameters go in a **sidecar** written next to each generated artifact:

```json
{ "artifact": "normal_promotion_trades_vault2026_d1f_20260829.json",
  "artifact_sha256": "1ee198a9f10387c8…",
  "asked_ema_period": 50, "effective_ema_period": 50,
  "ema_was_substituted": false,
  "asked_chandelier_atr_mult": 2.0, "chandelier_affects_decisions": false,
  "effective_stop_basis_atr_mult": 2.0, "ratchet": false, "max_hold_days": 5 }
```

Stage 5ZZZ-L's guard is also **corrected**. It compared hashes and fired on a true equivalence. The property that actually has to hold is *artifacts match if and only if the effective parameters match* — both directions — and that is what the guard and the tests now check.

**The baselines are byte-identical:** `f4d8eea7cd051b3d` / `c7eb5dd2e375316b` / `b1e85b2c9ab7019d`, asserted by a test.

---

## What this does to the record

**Nothing measured is invalid.** Every number came from a pipeline doing what it was written to do. What was wrong was the **label**.

| said | actually |
|---|---|
| Stage 5ZZZ-H/I/L "D-1 old params, ema=30" | **effective ema = 50**, stop basis 2.0 |
| Stage 5ZZZ-I "narrow retune, ema=10" | genuinely ema = 10 — correct as measured |
| Stage 5ZZZ-L "WFO winner ema=50 / mult=2.0" | **the same configuration as the D-1 old arm** |
| Stage 5ZZZ-L "full-stack numbers could not be produced faithfully" | **withdrawn** — they can, and they are the D-1 arm's |
| Stage 5ZZZ-L "Stage 5ZZZ-I is provisional" | **lifted** — its comparison stands |

**Neither Stage 5ZZZ-I nor Stage 5ZZZ-L needs a rerun.** Both need the label correction above, which this stage supplies.

And one thing worth stating plainly: **`SWING_TF_PARAM`'s `ema_period: 30` is not what the Track 1 artifacts run.** They run 50, which is `NormalR4Params.ema_period`'s own value. The substitution exists precisely to make the Rổ 4 basket run Track 1's trend period. It is deliberate — it was simply invisible.

### Which means Stage 5ZZZ-L's thresholds can now be evaluated

The WFO winner *is* the D-1 old arm, proven by identical artifacts, so its full-stack numbers are that arm's:

| threshold | outcome |
|---|---|
| **T1** net ≥ D-1 old in ≥3 of 4 OOS cells | **PASS** — identical in all four |
| **T2** Swing contribution ≥ $0 in **both** OOS windows | **FAIL** — 2025 +$3,906, **2026 −$464** |
| **T3** Calmar ≥ no-Swing in ≥1 OOS window, ≥60% in both | **FAIL** — 42% in 2025 (3.36 vs 8.05) and 42% in 2026 (3.76 vs 8.92) |
| **T4** MaxDD ≤ 115% of D-1 old | **PASS** — identical |
| **T5** winner wins ≥50% of folds | **PASS** — 5/10, five consecutive |

**Two of five fail, so Swing is still not promoted** — but now on evidence rather than on a blocked apparatus. Stage 5ZZZ-L's `KEEP_RESEARCH_ONLY` stands, and the full 48-candidate causal-D-1 search has a cleaner headline than it appeared to: **it converged on the configuration the route already runs.**

---

## Tests

`scratch/test_track1_stage5zzzm_param_obedience_20260829.py` — **17 passed**, covering the rule, its consequence on real artifacts in both directions, the sidecar, cache-key completeness (source and behavioural), and the untouched baselines.

**Mutation harness: 6/6 red**, files restored byte-identical.

| mutation | |
|---|---|
| M1 effective ema reported as the requested one | RED |
| M2 sidecar echoes the request instead of the effective value | RED |
| M3 substitution threshold moved off 30 | RED |
| M4 chandelier claimed to change decisions | RED |
| M5 substituted ema reported as un-substituted | RED |
| M6 the cache starts holding a parameter-dependent series | RED |

One test needed correcting first: it scanned `_swing_cache`'s whole source for "chandelier" and matched the word inside the docstring explaining why the cached ATR needs unsliced history. Rewritten as an AST walk with the docstring stripped — the same trap as Stage 5ZZZ-G, and the second time this session.

## Safety

```text
orders_possible False · blocking ['PAPER_SHADOW_EVIDENCE'] · scheduler pid 3000, not restarted
no broker call · orders dir ABSENT · TRACK1_ORDERS_APPROVED unset · confirmation intact
no live route params changed · SWING_TF_PARAM untouched · no gate opened
baseline promotion artifacts byte-identical (sha256 asserted by test)
```
