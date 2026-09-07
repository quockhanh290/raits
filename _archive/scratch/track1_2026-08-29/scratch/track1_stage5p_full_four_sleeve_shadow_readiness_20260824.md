# Stage 5P — full four-sleeve shadow readiness, and the dashboard cutover

**2026-08-24 ·** no scheduler started or stopped · no real IBKR · no order · no
`STOP_TRADING`, `STOP_TRADING.track1` or confirmation file touched · no live state written ·
no commit.

---

## Verdict: **READY_FOR_OPERATOR_TRACK1_ONLY_SHADOW_START**

The exact claim, no wider: **Track 1-only full four-sleeve shadow is ready to be started by
operator.**

Not claimed: paper/live readiness; broker-flat or orphan-STP cleanliness (account-level,
unmeasured against IBKR); safe-to-delete-legacy before the measured shadow period passes. And
one thing stated plainly rather than buried: **the slot runtimes against a live Gateway remain
unmeasured — the first shadow session IS that measurement**, and the acceptance gate below is
the judge it will face.

---

## 1. The inventory, verified whole

| Mode | Jobs | Composition |
|---|---|---|
| default | 60 | unchanged, asserted |
| `--track1-shadow` | 129 | unchanged, asserted |
| **`--track1-only-shadow`** | **95** | **70 strategy** (Calm 1 · Stress 24 · Normal-R4 23 · NKD 22) + **11 Track 1 safety** + **11 legacy drain safety** + **3 shared infra** + **0 legacy strategy** |

Parity true in all three modes (60/58, 129/127, 95/93). The probe fired **all 81 Track 1
children** with the runner mocked: `route=track1_candidate` on every one; the 70 strategy
slots all carry `--bar-provider ibkr` and none carries `--allow-orders`, `--port` or
`--window`; the 11 safety jobs all watch `live_positions.track1.json`.

## 2. The acceptance gate — committed before the evidence exists

`global_index/track1_shadow_acceptance.py`. A shadow period needs a judge whose questions were
fixed before the answers existed; a runbook paragraph gets re-read charitably after the fact,
a function returns the same named refusals every time. The thresholds are committed now, while
no shadow day exists to be graded.

| Check | Rule |
|---|---|
| coverage ×4 | each sleeve's window COMPLETE with a close record: 1 / 24 / 23 / 22 decided |
| slot gaps | **every registered slot id** wrote a ledger row — a count reads complete when one slot is silent and another fired twice; the ids do not |
| runtime | **p95 < 300 s required** (the slot cadence — at or above it, slots overrun each other); p95 < 240 s target, a miss warns |
| stalls | no single slot at or over 300 s, even with a healthy p95 |
| orders | no order mark in any record, **and** B1 still open, **and** no confirmation file |
| freshness | every explanation row carries a freshness proof (the 5Z contract) |
| explanations | present for the day |
| checkpoint | exists, names this route, cut on the judged day |
| checkpoint identity | **`not_checked_here` by name** — params-hash acceptance needs frames (`route_checkpoint.usable`); a green day must not read as having verified it |

Two deliberate hard edges, both tested: **a day without telemetry fails** — a day nobody
measured cannot be accepted as within budget — and `evaluate_period` accepts only when *every*
day is accepted.

The tests build one fully-green synthetic day under `tmp_path` and then degrade it one
dimension at a time — a missing sleeve close, a silent slot masked by a doubled one, p95 at
250 (warns) and 310 (fails), a single 301 s stall, an order mark, a confirmation file, stripped
freshness proofs, a wrong-route and a wrong-day checkpoint — requiring a **named** failure each
time. A format-drift guard writes one row through the real `window_ledger` and `slot_telemetry`
APIs and requires the gate's readers to parse it.

## 3. The dashboard cutover

**Measured first:** the dashboard had **no Track 1 reader at all**. Its positions endpoint
serves `live_positions.json` — and during a Track 1-only shadow the natural misreading is that
this is "the system's" state, when it is the *draining legacy book*.

**New:** `monitor/backend/track1_runtime_reader.py` + `/api/v1/track1-runtime` (additive).
It reads the Track 1 book, the route checkpoint, window coverage, slot timing, explanations,
the gate registry and the safety table — **Track 1 paths only**, held by an AST scan that
forbids the string `live_positions.json` anywhere in the module, and read-only, held by an AST
scan that forbids `open`/write calls. Absence is data: a missing Track 1 book reads as the
*expected* shadow state, not an error.

**Labelled:** `/api/v1/runner-positions` now carries `route: "legacy"` and a note pointing at
the Track 1 endpoint, so a legacy panel can exist but cannot present itself as Track 1.

The reader and the gate read the **same** path constants (asserted equal), and all of them
point at `global_index/track1_runtime/…` — never scratch, where ordinary cleanup deletes the
evidence a gate depends on (the 5K0 lesson, now mutation-guarded).

## 4. Operator page

```powershell
python monitor/ops.py restart --scheduler --track1-only-shadow
```

Ops sets `RAITS_TRACK1_ONLY`, `RAITS_TRACK1_SHADOW`, both runtime dirs, and **strips**
`TRACK1_ORDERS_APPROVED` from the child. No order path exists in this mode, and enabling
orders is not part of 5P. Legacy drain safety keeps watching `live_positions.json` until that
book is empty. Runbook section 12 carries the same page plus the gate table.

## 5. Legacy-removability, extended to the dashboard

With `global_index.run_live_day` made unimportable: the 95-job schedule builds, the dashboard
reader renders a green day, and the acceptance gate accepts it. The block itself is proven to
block (`importlib` route included).

---

## Mutations — 8/8 detected

```
P1  the reader opens live_positions.json           → the source scan reds      (on disk)
P2  the gate stops judging one sleeve              → the four-sleeve test reds
P3  the gate reads legacy's checkpoint             → the path-equality test reds
P4  Track 1 safety points at legacy's book         → the green day reds
P5  a legacy strategy job survives track1-only     → the inventory reds
P6  the safety table loses a job (count drift)     → the inventory reds
P7  --allow-orders on a strategy slot              → the argv probe reds
P8  the coverage path points into scratch          → the durable-path test reds (on disk)
```

**P3's first form went undetected (0/0/0) and the harness records why:** the green-day fixture
builds its checkpoint at the *same constant* the gate reads, so mutating the constant moved
fixture and judge together and the day stayed green. The faithful guard is the cross-module
path equality with the dashboard reader, which the mutation does not move. The sixth instance
of the shared-constant/unfaithful-mutation family across these stages, and the reason every
harness now states which side was at fault.

## Test results

| Suite | Result |
|---|---|
| **Stage 5P** `test_track1_stage5p_full_shadow_readiness_20260824.py` | **35 passed** |
| **Mutation harness** | **8/8 detected**, both production files restored byte-for-byte |
| Full sweep (5P + 5O + 5N + 5M-B/C/D + 5L + 3B + ops + mirror + dashboard backend) | **545 passed, 1 skipped**, then one stale stub fixed → dashboard suite **187 passed** |

`global_index/test_event_playback.py` **not run** — still the known hang.

One pre-existing test failed in the sweep and was fixed rather than left attributable:
`test_ops_restart_scheduler_stops_every_instance_before_starting_one` stubs `start_scheduler`
with a lambda narrower than the signature ops grew in Stages 5K/5M-D, so it raised a TypeError
from inside production code on the restart path — the same stale-stub family as the stage-4
`_run` lambda. Widened, suite green (187 passed).

Three of my own first-draft tests were wrong and are recorded as such: the read-only AST scan
flagged `str.replace` as a write (a name-based scan cannot tell it from `os.replace`; the
ambiguous name was dropped rather than special-cased), and the period test built its second
day into the same `tmp_path` as the first — pytest hands one tmp_path per *test*, not per
fixture use — overwriting the checkpoint and breaking both days at once.

---

## What the operator start will actually measure

The first shadow session produces the numbers nobody has: real slot runtimes for 70 strategy
slots against a live Gateway (three client ids now in play: legacy drain 1, Track 1 data 89,
Track 1 safety 90), the NKD overnight window on a real feed, and the daily coverage record.
The acceptance gate grades each day; `evaluate_period` grades the period; and only after that
do the account-level questions — broker-flat, orphan-STP, retirement itself — come up for
decision.

**This stage's claim ends at "ready to be started."**
