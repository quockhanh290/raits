# Stage 5ZZZ-R — the fix is in the running scheduler, and nothing has run on it yet

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

Three clocks, stated before anything that depends on them: machine **09:11 MDT**, market
**11:11 ET Saturday**, operator **22:11 VN**. Saturday is not a trading day, and that shapes
every verdict below.

---

## 1. The pid in the last report was already stale

Part A's first measurement contradicted the record. Stage 5ZZZ-Q closed with scheduler pid
3000; the process table said **9356**, started **08:59:41** — thirty-four minutes *after* the
last 5ZZZ-Q edit. The operations log says why:

```text
2026-08-29T08:59:37  scheduler: scan_ok=True found=[3000] -> kill_then_start
2026-08-29T08:59:42  backend:   scan_ok=True found=[10136] -> kill_then_start
```

An `ops.py` restart ran **from outside this session**. I cannot attribute it to a person from
the evidence, so I do not.

The consequence is the interesting part: **the Swing fix had already been live since 08:59:45**,
not since anything this stage did. The premise the stage was built on — "the running scheduler
may still have the old code in memory" — was no longer true by the time I read it.

## 2. Part A — every restart condition, measured

| condition | measured |
|---|---|
| mode restartable as track1-only-shadow | yes, already running with `--track1-only-shadow` |
| `orders_possible` | **False**, blocked by `PAPER_SHADOW_EVIDENCE` |
| slot child currently running | **0** |
| next slot imminent | no — next job of any kind is **Sunday 18:30 ET**, ~31 h away |
| legacy entry jobs | **0**, and the mode cannot register them |
| books | legacy 0, track 1 0, broker 0, working orders 0, orphans 0 |

One aside worth recording: my first scan for running slot scripts reported five matches. All
five were **my own measurement command matching its own token list** — the free-text substring
trap, self-inflicted, caught by reading the output instead of the count. The real answer is zero.

## 3. Part B — the restart, and a correction to the brief

```text
python monitor/ops.py restart --scheduler --track1-only-shadow --yes     exit 0
scheduler  9356 -> 34564
backend   31248 -> 44480
```

The brief expected the **backend pid to be unchanged**. It changed, and that is not a failure:
`monitor/ops.py:1474` defines `restart` as *"replace scheduler, its run_live_day children, **and
backend**"*. The command the brief specifies replaces the backend by design — and the external
08:59 run did the same thing. The expectation was wrong, not the outcome.

The restart also reconnected the **read-only** backend (`broker=connected`). No order path was
opened; `TRACK1_ORDERS_APPROVED` was removed from the child environment, and the startup line
reads `orders: impossible — blocked by PAPER_SHADOW_EVIDENCE`.

## 4. Part C — proving the code is live, not inferring it

Two independent lines, because a start-time argument alone is only an inference about what a
process *would have* imported.

**The process.** Scheduler 34564 started `09:11:11`, after the last 5ZZZ-Q edit (`08:25:46`),
and **zero** runtime `.py` files were modified after that start. Its startup log:
`Track 1 SHADOW slots registered: 71 (no orders — the route's gate refuses)`, with the legacy
`live_day` jobs removed.

**The behaviour.** The freshly started read-only backend serves:

```text
.market_view.sleeves.roska4_swing.strategy.diagnostics.regime_basis
    = "previous session (lag 1)"
```

That is a running process reporting the post-fix basis, and `global_nkd` agrees. I located the
exact JSON path rather than trusting a substring match on the whole payload — the same trap that
had already caught me once this stage.

## 5. Part D — nothing has run on it, and when it will

Saturday is not a trading day; Monday **2026-08-31 is**, confirmed from the repo's own calendar
(which also knows Labor Day, 2026-09-07, is not).

| sleeve | first post-fix slot (ET) | machine (MT) | operator (VN) |
|---|---|---|---|
| `global_nkd` | Mon 01:10 | **Sun 23:10** | Mon 12:10 |
| `roska4_calm` | Mon 09:32 decide / 10:02 observe | Mon 07:32 / 08:02 | Mon 20:32 / 21:02 |
| `roska4_stress` | Mon 10:35 *(gate 10:30)* | Mon 08:35 | Mon 21:35 |
| **`roska4_swing`** | **Mon 14:05** | Mon 12:05 | **Tue 01:05** |

The night-slot trap holds: NKD's first post-fix slot falls on the **machine's Sunday**.
The Swing slot — the one this whole sequence exists for — is **50.7 hours** after the
measurement.

## 6. Part E — parity, and the honest answer

All four sleeves: **`NOT_YET_OBSERVED`**.

> the newest live slot ran at 2026-08-28T12:46:22, before the newest relevant fix at
> 2026-08-29T08:21:23

No `UNKNOWN` was turned into a `PASS`. The pre-fix rows remain reported as informational, never
as a match, and nothing was rewritten. The `params_hash` gap named in 5ZZZ-Q still caps a
post-fix slot at `UNKNOWN` until parity joins the identity from the explanation record.

## 7. Part F — the gate, not moved

`PAPER_SHADOW_EVIDENCE` still blocks, and nothing here marked it satisfied. Two checks fail:

- **`no_failing_days`** — 5 FAIL days in the qualifying window, **0 allowed**
- **`calm_decision_evidence`** — missing 08-24/25/26, incomplete 08-27, present 08-28

The fact that matters more than either: **all five judgeable days (08-24…08-28) are pre-fix.**
The window holds five days and permits zero failures, so it cannot become entirely post-fix
until five post-fix trading days have run. Whether those days will pass is
**not predicted here** — it is `NOT_YET_OBSERVED`.

## 8. Tests

**13 new, all passing. Six mutations, six caught, none survived** — the basis map lying about
the sleeve, parity returning `PASS` on pre-fix evidence, an empty `params_hash` upgraded to a
match, a second scheduler appearing, the shadow flag disappearing, and legacy entry jobs coming
back. Each was broken in-process and restored; nothing on disk was edited.

The suite is built so it cannot pass on nothing: every list is asserted non-empty before it is
walked, and the "no legacy entry job" test first proves the token **does** find those jobs in
the legacy set, so a renamed job id cannot make the real assertion vacuously true.

One test failed on its first run and the failure was real: I had guessed both the path and a
field of the confirmation record. The record lives at the repo root and has **no order-approval
field at all** — it confirms legacy retirement. The test now asserts that absence, which is the
stronger claim.

### The five regression failures are not mine

`test_track1_stage5m_d_track1_only_shadow_20260823.py` fails five tests. All five pin literals
from **2026-08-23** that legitimately changed on **2026-08-27**: three SPY-ladder jobs joined
`shared_infra`, the operator signed the legacy-retirement confirmation, and the lead blocker
advanced from B1 to `PAPER_SHADOW_EVIDENCE`. The confirmation record is dated 2026-08-27 and
**none of those five tests reads the process table**, so a restart at 09:11 today cannot have
caused them.

I have **not** re-pinned them. Updating a pinned expectation asserts the new values are correct,
and that is the operator's call, not a side effect of a restart stage.

---

## 9. Answers

| question | answer |
|---|---|
| Was the restart safe to perform | **Yes** — every Part A condition measured and met |
| Did the restart happen | **Yes**, 09:11:05, exit 0 |
| Is the 5ZZZ-Q fix live | **Yes** — process evidence and behavioural evidence agree |
| Was it live before this stage | **Yes, since 08:59:45**, via a restart from outside this session |
| Post-fix slots observed | **0** — Saturday |
| Parity on post-fix slots | **`NOT_YET_OBSERVED`** |
| Evidence gate moved | **No** |
| Orders possible | **No** |

### Safety

```text
orders_possible          False
blockers                 ['PAPER_SHADOW_EVIDENCE']
orders sent              ZERO
orders dir               ABSENT
TRACK1_ORDERS_APPROVED   unset
confirmation             untouched, sha16 67504a1c8a31a6a4, dated 2026-08-27
swing paper override     present, valid, grants nothing
PAPER_SHADOW_EVIDENCE    not marked satisfied
scheduler                pid 34564, track1-only-shadow, EXACTLY ONE
backend                  pid 44480 (replaced by design — see §3)
params · gates · thresholds · strategy logic   untouched
runtime trading files edited this stage        NONE
runtime evidence rewritten                     NONE
```

**One thing for the operator.** The pid in the previous report was stale within the hour,
because something outside this session restarted the scheduler. That is worth knowing for its
own sake: reports that record a pid are describing a thing that moves. And Monday 14:05 ET is
the first Swing slot to run post-fix — the first session where the sleeve decides instead of
refusing. Orders stay impossible, but the shadow evidence written from Monday describes
different behaviour from every day currently sitting in the qualifying window.

### Unfinished, and named

- The `params_hash` gap caps a post-fix slot at `UNKNOWN`; parity must join the identity from
  the explanation record.
- The frozen `SWING_TF_PARAM` provenance still could not be reproduced.
- No day-level bootstrap on any OOS comparison.
- The dashboard's `track1-market-view` endpoint takes **over 300 s**, and `track1-runtime` ~23 s
  on both a cold and a warm call — so it is not a cold-cache effect. I have **no pre-restart
  measurement**, so I cannot say whether the restart changed it. Measured after, only.
