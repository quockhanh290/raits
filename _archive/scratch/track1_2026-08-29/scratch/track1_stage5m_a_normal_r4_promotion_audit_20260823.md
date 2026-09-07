# Stage 5M-A — Normal-R4 promotion audit

**2026-08-23 · read-only.** No scheduler, backend, or dashboard started or stopped · no IBKR
connection · no order · no `STOP_TRADING` or `STOP_TRADING.track1` touched · no confirmation
file · no live state file written · **no production code changed** · no commit.

---

## Verdict: **NOT_READY_BLOCKERS_FOUND**

Not because promoting Normal-R4 is risky. Because **the sleeve is not wired at all**, in six
named places, and every one of them is a hard refusal rather than a wrong answer.

To be explicit about the thing I was told not to claim: **Track 1 has no Normal-R4 slot today,
so nothing in this audit makes the shadow route "ready" for anything.** A shadow period started
right now still measures Calm and Stress only, exactly as the 2026-08-23 route audit found.

The good news is that the risks people worry about — process collision, IBKR contention, state
mixing, the order gate — are all measurable, and all of them come back manageable. The work is
wiring, not redesign.

---

## 1. Job inventory — before and after

| | flag off | flag on (today) | flag on (after 5M-B) |
|---|---|---|---|
| total jobs | 60 | 84 | **107** |

**Legacy in 14:05–15:55, measured from the built scheduler:** 23 jobs, `live_day` at 14:05 then
`live_day_1410` … `live_day_1555`, every 5 minutes with no irregular gaps. Each runs
`run_live_day --clusters all`.

**Track 1 today:** 1 Calm slot at 10:00, 24 Stress slots 10:35–12:30.

**Track 1 after 5M-B:** 23 swing slots mirroring the legacy cadence exactly — same minutes,
same 5-minute spacing.

---

## 2. The six blockers

| # | Where | Measured | Effect |
|---|---|---|---|
| **N1** | `track1_params.WINDOWS_ET` | keys are Calm and Stress only; `sleeves_at("14:05")` returns `[]` | `candidates()` raises `no_sleeve_at_this_instant` at every swing slot |
| **N2** | `track1_slots.TRACK1_SLOTS` | 25 slots, sleeves `{calm, stress}`; built by `_calm_slots() + _stress_slots()`, not derived from the window table | no swing slot exists to register — and the dashboard mirror reads this same tuple, so neither side has one |
| **N3** | `LiveTrack1Source._for_sleeve` | raises `sleeve_not_live` for `roska4_swing` | **there is no live candidate path for Normal-R4 at all** |
| **N4** | `track1_intraday.REQUIREMENTS` | keys are Calm and Stress only | the admission gate has no bar size, no decision window, no prior-RTH rule for swing — `window_verdict` can neither pass nor fail it |
| **N5** | `window_ledger.WINDOWS` | `expected_slots("roska4_swing")` is `None` | coverage can never be judged complete, so the runbook precondition a shadow period is measured against cannot turn green |
| **N6** | `track1_slots.REQUIRED_ENTRY_WINDOW` | `((10,35),(12,30))` — Stress only | documentation only; see §5, no new stop-repair exclusion is actually needed |

N3 is the one that matters. The refusal message is specific and correct — *"roska4_swing has no
Track 1 slot; it decides outside the 10:00 and 10:35-12:30 windows"* — which is the module
telling the truth about itself.

**One thing is already done and does not need building:** the route checkpoint's
`CHECKPOINTED_SLEEVES` is `["roska4_swing", "global_nkd"]`. The cross-day sleeves were designed
into the checkpoint from the start. No schema work.

---

## 3. Collision and runtime risk

**The mutexes are separate, deliberately.** `_slot_lock` serialises legacy because three legacy
entry points collide on IBKR clientId 1. Track 1 slots take a private `_t1_lock` that serialises
Track 1 against itself only. **Neither route can block the other**, so a Track 1 swing slot at
14:05 will not delay the legacy slot at 14:05, and will not be skipped by it.

That is the design intent, and it is also the risk: both fire.

**Legacy runtime, measured over 46 runs in the 2026-08-20 → 08-23 logs:**

| min | median | p90 | max | cadence |
|---|---|---|---|---|
| 187 s | **194 s** | 215 s | **291 s** | 300 s |

**Zero mutex skips in four days.** Legacy typically uses ~65% of its slot window — but the worst
observed run used **97%** of it. The headroom is real and thin.

**Track 1 swing slot runtime: NOT MEASURED.** No Track 1 slot has ever run in production — the
scheduler that is up predates all of this work. Anyone reasoning about "it's only 4 instruments
so it must be quick" is guessing, and 5M-B must measure it before the provider is switched on.

---

## 4. IBKR and provider risk

| | legacy | Track 1 |
|---|---|---|
| client id | **1** | **89** |
| port | 4002 | 4002 |

**No client-id collision** — measured from the CLI defaults on both sides. Two clients against
one Gateway is supported.

**A stale comment worth fixing in 5M-B.** `run_scheduler.py:1090` justifies the separate mutex
by saying *"the Track 1 shadow route opens no broker connection"*. That was true when it was
written. Stage 5I wired `--bar-provider ibkr`, and `build_bar_provider` calls
`broker.connect()`. **The sentence is now false.** The separate-mutex decision is still
defensible — different client id, no order path — but it is currently resting on a reason that
no longer holds, which is how a decision quietly loses its justification.

**Unmeasured residual:** IB historical-data pacing is enforced per account, not per client id.
Two routes requesting history in the same minute share that budget. Nothing in the logs measures
it because it has never happened.

Disconnection is handled: the entry point disconnects in a `finally`, with a comment noting that
a leaked connection per slot would be 25 a day.

---

## 5. State, checkpoint and switch behaviour

| Concern | Finding |
|---|---|
| positions book | `live_positions.json` vs `live_positions.track1.json` — **separate** |
| replay checkpoint | `replay_checkpoint.json` vs `.track1.json` — **separate** |
| checkpointed sleeves | already `["roska4_swing", "global_nkd"]` — **no work needed** |
| route stamping | `RAITS_ROUTE=track1_candidate` on Track 1 children, `legacy` otherwise |
| order gate | `blocking_now = ["B1_broker_account_or_legacy_retirement"]` → **orders impossible** |
| stop-repair sweeps | hours 2 and 14 already excluded; 12 excluded when Stress is live. A 14:05–15:55 window needs **no new exclusion** — it sits inside the already-excluded hour 14 |
| dashboard mirror | `schedule_status` imports `TRACK1_SLOTS` directly, so adding swing slots updates scheduler and mirror **together** |

**The kill switch deserves its own paragraph, because it is the opposite of what an operator
would assume.** Track 1 reads `STOP_TRADING.track1`. It does **not** read the root
`STOP_TRADING`. So the root switch — the one an operator places to stop legacy trading — does
**not** stop Track 1 shadow slots.

For a shadow measurement that is exactly right: legacy stops, Track 1 keeps observing, and the
evidence is clean. But it also means an operator who places the root switch expecting "the
system is stopped" will still have 23 Track 1 processes connecting to the Gateway every
afternoon. That belongs in the runbook in a sentence, not in someone's head.

---

## 6. Stop semantics — verified, with a correction to my own hypothesis

**The arm matches the candidate.** The stop goes live at entry day + 1 day + 14:05 in the
sleeve's own session clock. Hits strictly before that instant are **discarded**, and the first
bar at or after it arms the stop permanently. That is the sleeve's whole reason for existing:
the engine could have exited before the arm, live could not have.

**The gap-fill rule:** when the triggering bar is gap-eligible *and* opened beyond the stop, the
fill is the **open**; otherwise it is the **stop price**. Which bars are eligible is the fill
law.

### What I expected, and what the measurement said

I reasoned that the 14:05 bar could never be gap-eligible under the production law, because a
continuous session has no break longer than 15 minutes before it — and therefore that the
production law would always book the optimistic stop price at the arm.

**Measured on MES, vault2026:**

| | sessions with a 14:05 bar | arm bar gap-eligible |
|---|---|---|
| production law | 194 | **36** |
| artifact law | 194 | 194 |

**The hypothesis was wrong.** The arm bar is gap-eligible under the production law in 36 of 194
sessions — thin stretches where nothing printed for more than 15 minutes.

### What the two laws actually cost this sleeve

Running the full R4 sleeve on vault2026 under both laws:

```
artifact   : 81 trades
production : 81 trades
differing  :  0
```

Zero. Consistent with the three-blockers measurement, which put vault2026 swing at 0 trades
changed and the whole-book delta at $0 to +$6 over seven years.

### The residual worth carrying into 5M-B

On the other **158 sessions** the arm bar is not gap-eligible. If the market is already through
the stop at 14:05 on one of those, the backtest books the **stop price** while a live STP armed
at that moment fills at the **prevailing market**. Measured cost on this window: zero trades. It
is structurally present, it is small, and it is an execution-semantics note for the 5M-B
runbook — not a blocker.

**Identity separation holds.** Live and shadow take the production law through
`track1_params.LIVE_FILL_LAW`; artifact reproduction asks for `FILL_ARTIFACT` by name. Stage
5M-1 closed that, and a static scan over all 115 production modules finds no implicit path back.

---

## 7. Recommended path for 5M-B

| Option | Timing fidelity | Operational risk | Verdict |
|---|---|---|---|
| **A** direct slots at the same minutes, provider on from day one | exact | **highest** — two children per minute against one Gateway, unmeasured | no |
| **B** same minutes, shadow only, separate mutex, **`--bar-provider none` first** | **exact** | low, then medium when the provider is switched on | **recommended** |
| **C** offset by 1–2 minutes | off by one bar | lower | rejected — see below |
| **D** piggyback / serialise behind legacy | unbounded delay | low | rejected — see below |

**Recommended: B, in two steps.**

1. Wire the six gaps and register the 23 slots with `--bar-provider none`. Every slot refuses
   with `no_bar_provider`, writes a ledger row, and costs one short-lived process — which is
   how the runtime and the collision behaviour get **measured** instead of estimated.
2. Only once step 1 has a few days of timing data, switch the provider to `ibkr`.

**Why exact timing and not an offset.** The measured rule arms at 14:05 and takes entries on the
resume bar; the timing *is* the sleeve. An offset slot is a different rule that resembles it, and
the shadow evidence it produced would not be evidence about the thing that was backtested.

**Why not serialise behind legacy.** Legacy's median run is 194 s against a 300 s cadence. A
Track 1 slot queued behind it would decide 3–5 minutes late, or be skipped — and a sleeve whose
entry latency is unbounded is not the sleeve that was measured. The separate mutex already
avoids this; the cost is that both processes run, which is precisely what step 1 exists to
measure.

**Also in 5M-B, small and cheap:** correct the stale "opens no broker connection" comment,
declare the swing entry window alongside the Stress one, and add the runbook sentence about the
root `STOP_TRADING` not stopping Track 1.

---

## What this audit does not claim

Normal-R4 has been **audited**, not promoted. There is no Track 1 slot for it, no live candidate
path, and therefore no shadow evidence — and none can exist until 5M-B closes N1 through N5.

Track 1 shadow today measures **two sleeves of four**. That has not changed.
