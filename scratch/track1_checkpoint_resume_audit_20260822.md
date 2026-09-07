# Track 1 — checkpoint/resume design audit (read-only) — 2026-08-22

Read-only. No scheduler, runner, monitor backend or IBKR connection was started. No production file
was modified. No Track 1 route was created. Nothing committed.

---

## Headline: the "64 no usable checkpoint" figure does not mean what the plan assumed

The route plan treats `91 matched / 0 diverged / 64 skipped` as *"checkpoint coverage is incomplete
and 64 skipped comparisons lack reason codes."* Measured against the logs, that is not the shape of
it.

| log day | matched | skipped | coverage |
|---|---:|---:|---:|
| 2026-08-06 | 0 | 16 | **0%** |
| 2026-08-07 | 6 | 48 | **11%** |
| 2026-08-10 → 2026-08-21 (10 trading days) | 85 | **0** | **100%** |
| blended | 91 | 64 | 59% |

**All 64 skips are on two days, and there have been none in the ten trading days since.** The 59%
blend mixes two bootstrap days into ten clean ones; quoting it as "coverage" understates the current
state by a wide margin.

And the cause is not unknown — it is documented, in the code that fixed it.

---

## 1. Inventory: what the checkpoint stores today

`global_index/replay_checkpoint.py`, `DEFAULT_PATH = "global_index/replay_checkpoint.json"`,
`SCHEMA = 1`.

```
{"schema_version": 1,
 "instruments": {
   "MES": {"last_day": "2026-08-20",
           "fingerprint": "3367423:e36825ea00e221ae",
           "params": "chandelier_atr_mult=2.5;ema_period=30;max_hold_days=5",
           "pos": null}, ... }}
```

| Field | Meaning | Source |
|---|---|---|
| `last_day` | newest session the entry describes | `advance_day` (`:133`) |
| `fingerprint` | `"<rowcount>:<content hash>"` of history through `last_day` | `fingerprint` (`:34`), content-derived, tz stripped, measured 0.54 s on 2.8 M rows |
| `params` | `ema_period`, `chandelier_atr_mult`, `max_hold_days` as one readable string | `_param_id` (`:104`) |
| `pos` | the open position at the end of `last_day`, or `null` | `_pos_to_json` (`:63`) |

`usable()` (`:173`) accepts only when **both** the fingerprint and the param string match, and
refuses an entry with no recorded params rather than accepting it.

### Identity keys that exist today

**Instrument only.** That is the entire key space.

### Identity keys that are missing for a separate Track 1 route

| Missing key | Why Track 1 needs it |
|---|---|
| **route** | there is one file, one namespace. Two routes on the same instrument collide |
| **cluster / sleeve** | Track 1 puts MES and MNQ in *two* sleeves at once (Normal-R4 and Calm A). One entry per instrument cannot hold two positions |
| **stop configuration** | `params` covers ema/mult/max_hold and **nothing else**. Track 1's Normal-R4 differs from legacy by `stop_basis=2.0`, `ratchet=False`, `arm_hours=14:05` — **none of which appear in `params`** |
| **filter identity** | the R4 context filter and the SPY short filter change which trades exist; neither is in `params` |
| **regime/label identity** | `hmm_fit_end`, the regime CSV, and the Calm gate all decide the position; none is captured |
| **data-source identity** | which parquet produced the history. The fingerprint pins the *content*, not which file it came from |
| **route-level `pos`** | `pos` is a single swing position dict. Stress and Calm A are intraday with different state |

**The concrete hazard**, not hypothetical: Track 1's Normal-R4 runs ema **50** where legacy runs
**30**, so `_param_id` would differ and `usable()` would refuse — good. But Track 1 *also* changes the
stop basis, the ratchet and the arming, and **those three are invisible to `_param_id`**. A future
Track 1 variant that kept ema 50 and changed only the stop would silently resume a checkpoint
computed under a different stop. `usable()`'s own docstring states the principle — *"Unknown is not
the same as equal"* — and the param set is currently narrower than the thing it is protecting.

### One more structural fact

`ckpt.save(updated, path)` (`:95`) writes the **whole** entries dict. Two routes sharing one file
means whichever writes last rewrites the other's entries. There is no per-key merge.

And the checkpoint is advanced **only inside the `--shadow-resume` block** of `run_live_day`
(`:413`–`:574`). Checkpoint maintenance is coupled to the shadow feature being switched on. A
resume-primary route must invert that: the checkpoint becomes the thing that must always advance, and
the shadow becomes the optional check.

---

## 2. The 64 skips, classified from the logs

| category | count | what it is |
|---|---:|---|
| **different row count** | **48** | stored fingerprint counts fewer bars than the recomputed one |
| old message format, no diagnostic fields | 12 | the earliest lines; unclassifiable from the record |
| same row count, different content hash | 4 | bar content changed under the entry without changing length |

Distribution is the tell:

| day | MES | MNQ | MYM | M2K | **MNKD** |
|---|---:|---:|---:|---:|---:|
| 2026-08-06 skipped | 4 | 4 | 4 | 4 | **0** |
| 2026-08-07 skipped | 12 | 12 | 12 | 12 | **0** |
| 2026-08-07 matched | 1 | 1 | 1 | 1 | **2** |

Measured row-count deltas: **−552, −553, −554**.

### The cause is already written down, in the fix

`advance_day`'s docstring (`replay_checkpoint.py:133`) names this exact incident:

> *"Advancing on the spliced frame therefore writes a fingerprint over a day the parquet only half
> holds, and tomorrow's append changes it. That is not hypothetical: on 2026-08-07 every slot rejected
> the checkpoint for all four Rổ 4 instruments, **554 rows short**, and the session gathered no
> evidence at all."*

And it explains why MNKD survived: its Tokyo day closes at 00:00 JST = 15:00 UTC, **before** the
13:45 ET parquet append, so its history through `last_day` was already fixed. Every one of those
claims checks out against the logs: four R4 instruments only, zero MNKD, deltas of −552 to −554.

The fix — take the parquet's second-to-last session, on the parquet's own clock — is in place, and
coverage has been 100% since 2026-08-10.

### What is still missing, and it is not what the plan said

Reason codes are **not** the gap on today's code. The current message already logs `luu=` (stored
fingerprint), `tinh=` (computed) and `params=` (stored). Two real gaps remain:

1. **The params-refusal path has never fired in production.** Every recorded skip is a fingerprint
   mismatch. The `params != stored` branch of `usable()` — the one that protects against resuming
   under different engine settings, added 2026-08-17 in commit `c91f14f` *"Stop the replay checkpoint
   being trusted further than it can prove"* — has **zero** production exercises. Before resume goes
   primary it must be fired at least once deliberately, offline, and observed to refuse.
2. **A refusal still cannot say *which* of the four conditions in `usable()` fired.** It returns
   `None` for: no entry, unparseable `last_day`, fingerprint mismatch, params mismatch. The caller
   infers the reason by comparing the logged fields. A one-word `reason` in the record would remove
   the inference — the categories above had to be reconstructed by string-diffing two hashes.

**Suggested reason codes** (for the Track 1 route's own checkpoint, not a legacy change):
`no_entry`, `bad_last_day`, `fingerprint_rowcount`, `fingerprint_content`, `params_mismatch`,
`route_mismatch`, `schema_mismatch`.

---

## 3. Route-specific checkpoint design

### Separation

| | legacy | Track 1 |
|---|---|---|
| path | `global_index/replay_checkpoint.json` | **`global_index/replay_checkpoint.track1.json`** — a distinct file, passed by the existing `--checkpoint-path` flag, so no new CLI surface is needed |
| key | `instruments[inst]` | `routes[route].sleeves[sleeve].instruments[inst]` |
| writer | the `--shadow-resume` block | the route's own step, unconditionally |

**No shared mutable state**: separate file, separate process invocation, separate `--checkpoint-path`.
Because `save()` rewrites the whole dict, sharing one file is not merely untidy — it is a lost-update
bug waiting for the first concurrent slot.

### Identity, widened

`schema_version` should go to **2** for the Track 1 file so a v1 reader refuses it outright (`load()`
already refuses on schema mismatch, `:88`).

Each entry carries:

| key | why |
|---|---|
| `route` | `"track1_candidate"`; a mismatch is a hard refusal |
| `sleeve` | `roska4_swing` / `roska4_stress` / `global_nkd` / `roska4_calm` |
| `instrument` | as today |
| `last_day` | as today |
| `fingerprint` | as today — content-derived, unchanged |
| **`params_hash`** | see below |
| `params` | keep the readable string too. `_param_id`'s docstring is right that a human-readable entry beats eight hex digits when a refusal has to be explained — so carry **both**: the hash decides, the string explains |
| `pos` | per sleeve, not per instrument |
| `data_source` | the parquet path/identity the history came from |

### `params_hash` — what must be inside it

Everything that changes which position the bars produce. Today's `params` covers three of these:

- ema period, chandelier multiple, max hold *(covered today)*
- **stop basis and whether the stop is entry-anchored** *(missing)*
- **ratchet on/off** *(missing)*
- **arm hour and its timezone** *(missing)*
- **the filter set** — R4 context filter thresholds, SPY short filter *(missing)*
- **regime identity** — `hmm_fit_end`, regime CSV identity, the Calm gate's lag *(missing)*
- **cluster caps and the family cap** — they change which trades are *taken*, so they belong in the identity of any checkpoint that stores an admitted position *(missing)*
- **slippage/cost assumption** *(missing)*

A stale checkpoint that survives a parameter change is the one failure mode that is *fast and wrong*,
which is precisely the trade the module says it refuses to make.

---

## 4. Equivalence checks — resume vs full-replay oracle

Compare the resumed state against a full replay over the same window, per sleeve per instrument.

### Open position, at the comparison instant

`instrument · sleeve · direction · qty/contracts · entry_day · entry_time · entry_price · stop ·
target (Stress) · extreme/ratchet state where the engine carries it`

### Every trade that closed after `last_day`

`instrument · sleeve · direction · qty · entry_day · entry_time · entry_price · exit_day · exit_time ·
exit_price · exit_reason · points · pnl · hold_days`

Trade lists compared **as ordered sequences**, not as sets: two books with the same trades in a
different order are not the same book once a cap admits by priority.

### Tolerances

- prices and P&L: **exact** to the stored rounding (`round(x, 2)`), no epsilon. The existing
  shadow comparison already achieves exact equality 91 times out of 91 — a tolerance introduced now
  would only hide a regression from that standard.
- timestamps: exact.
- counts: exact.

### How a mismatch blocks promotion

1. **Any** field mismatch on **any** instrument/sleeve = the day fails.
2. Promotion to resume-primary requires **N consecutive clean trading days with 100% comparison
   coverage** — a skipped comparison counts as *not clean*, not as neutral. That rule is what the 64
   skips would have caught: 2026-08-06 had **zero** comparisons and would have read as "no
   divergence".
3. A single divergence resets the counter to zero and blocks promotion until the cause is named.
4. The oracle keeps running on a schedule after promotion (R7). A post-promotion divergence is a
   rollback trigger, not a ticket.

---

## 5. Fail-closed behaviour

The rule throughout: **a route that cannot prove its state does not trade.** Never "assume flat" —
assuming flat when a position is open is the one error that opens a second position.

| Condition | Detection | Behaviour |
|---|---|---|
| **Missing checkpoint** | `usable()` → `None`, `no_entry` | No entries. Existing positions are still managed from broker + position file. Emit a distinct outcome; do **not** silently fall back to full replay unless that fallback is explicit, telemetered and inside the runtime gate |
| **Stale checkpoint** | `last_day` older than a declared max age, or fingerprint mismatch | Same as missing. A controlled repair (bounded full replay) may run **once**, with its runtime measured; if the repair itself breaches the runtime gate, fail closed instead |
| **Param / hash mismatch** | `params_hash != stored` | **Hard refusal, no repair.** Someone changed the strategy; resuming is wrong by definition. Requires an explicit bootstrap |
| **Divergence vs oracle** | equivalence check fails | Block new entries for the route immediately; keep managing open positions; alert. Do not let the next slot "pick it up" — that is only valid for idempotent state, and a divergence means the state is not trustworthy |
| **Broker/state mismatch** | the existing B3 reconcile | Already halts new entries. Track 1 must reconcile **route state + position file + broker** before any entry, and route state must not be able to claim a position the broker does not show |
| **Host slept through a Track 1 window** | see §8 | The window is **missed, not empty**. Record it as unavailable; never let it read as "no signal" |

One property worth stating because it is easy to lose: today an unusable checkpoint is **safe** — the
shadow comparison is skipped and the trading path is unaffected. Under resume-primary that inverts:
an unusable checkpoint becomes a *trading* event. Every one of the rows above changes from "quiet" to
"must be loud".

---

## 6. Which Track 1 sleeves can run incrementally

| Sleeve | State needed to resume | Bars needed since checkpoint | Enough without full replay? |
|---|---|---|---|
| **Normal-R4 filtered** | open position (dir, entry, entry_day, stop, extreme), plus the daily-ATR series and the EMA-50 warmup | 5-minute bars in 14:00–15:55 for the days since `last_day`, plus enough lead-in for EMA-50 and ATR-14 | **Yes.** This is exactly what `backtest_swing_tf(resume_pos=…, resume_after_day=…)` already does, and it is the path with 91/91 matches. Note the lead-in requirement the engine docstring insists on: the frame must start at least one session before the replay day or the first bar loses its gap flag |
| **Current NKD / MNKD** | same shape, Tokyo clock | same, on the Tokyo session | **Yes**, and it is the strongest case — MNKD was the one instrument whose checkpoint survived 2026-08-07 because its day closes before the ET append |
| **Stress-MNQ `mnq_only_g3_q7`** | **no cross-day state at all**: the setup is built from the current day's 09:30–10:30 bars on all four R4 instruments, plus each instrument's prior RTH close for the gap | today's bars only, plus one prior session close per instrument | **Yes — trivially.** This sleeve does not need a checkpoint; it needs *today's* bars. The risk is the opposite one: it cannot be resumed at all if the window was not observed (§8) |
| **Calm A PCLoc + ATR15** | prior **completed** RTH session shape (close-location, return, high/low) per instrument, the D-1 Calm label, and today's 09:30 open | prior session daily aggregates + today's bars from 10:00 | **Yes**, and it is precomputable: every input except today's open is known before the session starts. D-1 context is sufficient by construction — the gate is explicitly D-1 causal |

**Summary.** Two sleeves (Stress, Calm A) are same-session and need **no** historical checkpoint —
only today's bars and a small D-1 context. Two sleeves (Normal-R4, NKD) are cross-day and already
have a working resume path. So resume-primary is a natural fit for Track 1, and **more of Track 1 is
checkpoint-free than the legacy route is.**

The consequence for design: the Track 1 checkpoint only needs to carry the two swing sleeves. Stress
and Calm A need a *different* kind of state — an observation record for the day, which is §8.

---

## 7. Runtime and telemetry implications

### What telemetry should measure under resume-primary

The existing phase set stays useful but its centre of gravity moves. `run_day` is currently the big
opaque block; under resume-primary the interesting split is inside it:

| new phase | why |
|---|---|
| `ckpt_load` | cheap, but a corrupt/missing file changes everything downstream |
| `ckpt_verify` | fingerprint is measured at 0.54 s on 2.8 M rows — worth confirming it stays there |
| `bars_fetch_incremental` | the whole point of the route is that this is small |
| `sleeve_update` (per sleeve) | where Track 1's added cost actually lands |
| `ckpt_advance_write` | must always run under resume-primary; a failure here is a trading concern, not telemetry |
| `oracle_replay` | only on days the oracle runs; keep it separate so it never contaminates the p95 |

### Are today's phases enough?

**For the legacy baseline, yes** — `frozen_check / data_load / hmm_labels / setup / ibkr_connect /
runner_init / run_day / shadow_replay` answers "where does the current 191 s go" at the granularity
the runtime gate needs.

**For resume-primary, no**, but not yet: the sub-phases above belong in the Track 1 route's own code,
which does not exist. They should be written *with* it, not retrofitted.

### When deeper markers inside `runner.py` / `signal_layer.py` become necessary

Exactly one trigger, and it is a number: **when `run_day` alone threatens the p95 gate.** If Track 1
shadow lands under 240 s with `run_day` comfortably inside it, instrumenting hot trading code buys
nothing and costs a diff in the most load-bearing file in the tree. If `run_day` grows toward 300 s,
a single opaque number cannot be optimised and the markers become mandatory. That is gate G5 as
already written.

---

## 8. Operational availability — the thing a checkpoint cannot fix

### The claim, and it holds

**A checkpoint cannot repair an observation the host never made.**

A checkpoint stores *derived state* — a position and the fingerprint of the history that produced it.
It can rebuild derived state from bars that exist. It cannot manufacture the fact that at 11:07 ET
MNQ broke the 09:30–10:30 low, if nothing was running to see it and act on it.

Concretely, per sleeve:

- **Normal-R4 / NKD**: a missed slot is genuinely recoverable. The engine's state model is idempotent
  — the next slot computes the same desired position — and a suspend costs entry *latency*, which the
  22-slot continuous window exists to bound.
- **Calm A**: single-shot at 10:00 ET. A suspend across 10:00 loses the entry outright. Recoverable in
  principle at a later slot, but the fill would be at a different price, which is the same class of
  error as the 2026-08-04 max-hold.
- **Stress-MNQ**: **not recoverable.** The entry is the break of the 09:30–10:30 low, between 10:35
  and 12:30. If the host is asleep when the break happens, the trade did not happen. Re-running later
  finds a break that already occurred and would enter at a price that has moved — the exact
  "one-shot execution at the wrong price" failure that cost −20.2% in the legacy engine and was ruled
  a design error, not a tolerance question.

The 2026-08-04 incident is the precedent: the job did not run, and nothing downstream could tell the
difference between "no position was due" and "we never looked". That is why §5 refuses to let a
missed window read as "no signal".

### Where to record it, so it fails closed

Today there is nowhere. `slot_timing_*.jsonl` records `skipped_mutex` and `skipped_preflight` — both
are *scheduler decided not to run*. A host suspend produces **no record at all**, because no process
was alive to write one.

Three places, cheapest first:

1. **A window-coverage ledger, written by the route itself.** At the start of each Track 1 detection
   window the route writes `window_open`, and at the end `window_closed` with the count of slots that
   actually ran. A window whose expected slot count was 24 and observed 9 is *incomplete* and the day
   is marked unusable for that sleeve. This is the one that fails closed by construction: absence of
   `window_closed` is itself the signal.
2. **Reconcile against the scheduler's own stall record.** `HEARTBEAT STALLED` already exists and, as
   measured this session, matches real OS suspends **28 out of 28**. A stall overlapping a Track 1
   window marks the window unavailable. This costs nothing to add because the evidence is already
   being written.
3. **Cross-check against the OS.** The Windows Power-Troubleshooter log records every suspend with
   sleep and wake times, and it is authoritative where the scheduler's is not — it captured 39
   suspends in the window against the scheduler's 28. A daily read of it would catch suspends the
   scheduler could not report because it was not running.

Whatever the mechanism, the requirement is one sentence: **a Track 1 sleeve must be able to say "this
window was not observed", and that state must be distinguishable from "this window produced no
signal".** Today it cannot, and R0/G3 is the reason that matters.

---

## 9. Verdict on the resume-primary direction

**The direction is sound and the evidence is stronger than the plan credits — but the promotion
criteria in the plan need one correction and two additions.**

What holds:

- Resume-primary fits Track 1 better than legacy, because **two of its four sleeves need no
  historical checkpoint at all** — they are same-session with D-1 context.
- The resume path has 91/91 exact matches and 100% comparison coverage for 10 consecutive trading
  days.

The correction:

- **R1 as written ("skipped comparisons have reason codes") is aimed at a problem that is already
  fixed.** The 64 skips are one bug, on four instruments, on two days, caused by advancing the
  checkpoint over a half-held parquet day — diagnosed and fixed, with the fix's own docstring naming
  the incident. R1 should instead require: *100% comparison coverage sustained over the declared
  window, with a skipped comparison counted as a failed day rather than a neutral one.*

The additions:

- **The params-refusal path has never fired in production.** It must be exercised deliberately and
  observed to refuse before resume goes primary.
- **`params_hash` must cover more than `params` does today** — stop basis, ratchet, arm hour, filter
  set, regime identity, caps, cost. Otherwise Track 1 can change its stop and silently resume state
  computed under the old one.

And one thing the checkpoint design cannot carry, which belongs in R0: **the Stress sleeve has no
recoverable state for a window the host did not observe.** No checkpoint work substitutes for an
always-on host.

## Artifacts

- this report, and `scratch/track1_checkpoint_resume_audit_20260822.json`
