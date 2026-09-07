# Stage 5ZY-PRE — the code is right and the running scheduler has never heard of it

**2026-08-27, ET 03:45–04:40.** Read-only precheck. Nothing implemented that sends · no orders ·
no confirmation file · nothing written to `track1_runtime/orders/` · no runtime file edited by
hand · **nothing restarted** · **no claim that Calm has live decision evidence.**

---

## The answer in one line

**The system is NOT ready to observe the next live Calm window, and it is currently in a state
that is worse than before Stage 5ZX — until the scheduler is restarted.**

---

## 1. What the machine is actually running

| | |
|---|---|
| scheduler process | one, PID 11788 |
| started | **2026-08-26 22:07:37 ET** |
| mode | track1-only-shadow, port 4002 |
| broker | connected, quote age 5.8 s |
| orders possible | **false** |
| blocking | B1, PAPER_SHADOW_EVIDENCE |
| confirmation file | false |
| `TRACK1_ORDERS_APPROVED` | false |
| B1 measurement | PASS, taken 2026-08-26 11:34 ET, **expires 2026-08-27 11:34 ET** |

Every file Stage 5ZX changed was written at 02:08 ET or later — **four to five hours after that
process started**. The scheduler built its job table once, at boot, and has been holding it in
memory ever since.

Its own log says so, in its own words:

```text
2026-08-26 20:07:39  Track 1 SHADOW slots registered: 70
```

Seventy, not seventy-one. And across every scheduler log this project has, the strings
`CALM_DECIDE` and `CALM_OBSERVE` appear **zero** times.

## 2. The two jobs are registered in the code and in nothing that is running

Built from real scheduler construction, this minute:

```text
track1-only total jobs   102     (expected 102)
track1 strategy slots     71     (expected 71)
track1_calm_decide_0932   registered = True
track1_calm_observe_1002  registered = True
track1_calm_1000          registered = False
```

All four hold — **in the code**. In the live process, the opposite of all four is true. The last
Calm slot production actually launched was, on 2026-08-26 at 10:00 ET:

```text
-m global_index.run_live_day_track1 --source live-shadow --sleeve roska4_calm
   --slot-id TRACK1_CALM_1000 --bar-provider ibkr --regime-csv spy_daily_live.csv
```

## 3. Leaving it alone is now the dangerous option

This is the finding that matters, and it was measured rather than reasoned about.

At 10:00 ET today the live scheduler will launch `TRACK1_CALM_1000`. That slot id no longer
exists. The child refuses — and the refusal happens **before the window ledger is opened**:

```text
RAISED ShadowRefused: unknown_slot: 'TRACK1_CALM_1000' is not a roska4_calm slot;
                      known: ['TRACK1_CALM_DECIDE_0932', 'TRACK1_CALM_OBSERVE_1002']

ledger files written: 0
```

Yesterday Calm refused too — but it refused *inside* the ledger, and left a row saying so. Today
it would leave nothing at all, and the audit reads nothing at all as **"nobody looked"**. That is
strictly worse than a recorded refusal, and it is precisely the failure mode Stage 5Q-3 was built
to eliminate for a different refusal.

So the restart is not a tidying step. It is the difference between a window that reports why it
failed and a window that vanishes.

## 4. When it is safe to restart, and what to watch

Measured from the schedule, as of 03:50 ET:

```text
04:20 ET   stop_repair_0420 / track1_stop_repair_0420
06:20 ET   stop_repair_0620 / track1_stop_repair_0620
08:20 ET   stop_repair_0820 / track1_stop_repair_0820
09:31 ET   maxhold_exit / track1_maxhold_exit
09:32 ET   TRACK1_CALM_DECIDE_0932      <- the first thing that has never run
10:02 ET   TRACK1_CALM_OBSERVE_1002
```

Quiet gaps wide enough to restart in: **04:21–06:20, 06:21–08:20, 08:21–09:31 ET**. The restart
must happen **before 09:32 ET** or the decide half is missed for the day; and if it is going to
be missed, it is better missed than half-done, because a decide phase that never ran and an
observe phase that runs anyway produce a refusal row saying there was no decision to observe —
which is correct, and is not evidence.

**One adjacency to know about.** The decide slot fires one minute after `track1_maxhold_exit` —
the job that wrote the Track 1 book at 09:31:13 on 2026-08-26 and caused the corruption Stage 5ZS
repaired. Measured from the live logs, that job takes **1 to 13 seconds**, so the decide slot has
about **47 seconds of clearance** at the worst observed runtime. They also use different broker
identities — the safety job takes client 90, a slot child takes 89 — so they cannot collide on a
connection. Thin but real, and worth watching on the first day rather than assuming.

## 5. The runtime filesystem, as a baseline to compare against afterwards

```text
global_index/track1_runtime/shadow_intent    ABSENT      <- the phases have never run
global_index/track1_runtime/orders           ABSENT      <- must stay absent
trade_log.track1.jsonl                       0 rows      <- the route has never traded
live_positions.track1.json                   08-27 02:55:42 ET
replay_checkpoint.track1.json                08-27 02:55:42 ET
preflight_state.json                         08-26 13:47:09 ET
live_positions.json (legacy)                 08-26 09:31:11 ET
```

The book and checkpoint moved together at 02:55:42 ET — the overnight Nikkei window closing and
the route writing its own state. The book came through it still carrying schema 2, the route
stamp, no foreign fields and no positions. That is the **fourth** window close the Stage 5ZS
repair has survived.

No trade-log row mentions an intent, and nothing under the runtime tree was edited by hand.

## 6. What the evidence gate says, and what it must not be read as saying

```text
judgeable days on record : 2026-08-24, 2026-08-25, 2026-08-26      (3 of 5 required)

calm decision evidence   :
    2026-08-24  missing
    2026-08-25  missing
    2026-08-26  missing
    counts the DECISION only — never acceptance, fill or slippage

Calm days counted: 0        no day carries an execution label
```

All three read *missing* because all three predate the stream. **Calm contributes nothing yet, and
this precheck claims nothing otherwise.**

Two things worth pulling out of the per-sleeve detail, because they change what the next window
means:

- On 2026-08-26 the route reached **PASS on two of four sleeves** — the stress and swing sleeves
  both passed. Calm was one of the two that did not.
- Calm's recorded reason on that day was `gate_refused: partial_coverage, decision_bar_absent` —
  and that run happened **before** the Stage 5ZU timing fix landed. So the most recent live Calm
  result does not measure the current code at all. **No live Calm window has ever run against
  either the 5ZU fix or the 5ZX phases.**

## 7. The unsplit sleeves, checked against production rather than against a fixture

Stage 5ZX narrowed `--phase` to slots that have one, and the claim was that the other three
sleeves' command lines are unchanged. Compared against what the live scheduler has actually been
launching:

```text
LIVE : ... --sleeve roska4_stress --slot-id TRACK1_STRESS_1035 --bar-provider ibkr --regime-csv ...
NEW  : ... --sleeve roska4_stress --slot-id TRACK1_STRESS_1035 --bar-provider ibkr --regime-csv ...
IDENTICAL
```

And across **205 Track 1 child launches** in every scheduler log this project holds, the string
`--allow-orders` appears **zero** times. Across all 71 slots the new code would build, it appears
zero times.

## 8. A gap this precheck found and closed

Deleting the phase branch from the scheduler left **every test in the corpus green**. The slot
table knew about phases; the gate knew about phases; nothing asserted that the thing which starts
processes passes one. A mechanism built and its wiring left unproven — the fifth time in this
programme.

Closed by a test that fires the real registered jobs with the launcher replaced and reads the
argv they build. It is one test and it catches four separate collapses:

```text
--source live-shadow removed                          RED
the phase branch deleted                              RED
--allow-orders smuggled into the argv                 RED
a phase leaking into the three unsplit sleeves        RED
```

## 9. Two failures this precheck owns, repaired

Both were good assertions that Stage 5ZX broke, and both were repaired without loosening them.

- **The dashboard fact pin** is bidirectional — it fails if a row is rendered that the list does
  not know about. Stage 5ZX added a row and did not declare it, and the pin caught exactly that.
  The row is now declared, which also brings it under the per-row rendering check.
- **The argv extractor** in an older suite read the launcher's first argument only when it was a
  single list literal. The narrowing in Stage 5ZX made it a concatenation, so the extractor
  stopped finding the call at all and reported "no launch call" — which reads like the wiring was
  removed rather than reshaped. It now flattens a concatenation and reports **both** branches of
  a conditional, so a reader asking "can this argv carry an order flag" still gets a truthful
  answer. Widening the reader did not loosen what reads it: a removed flag still disappears.

## 9b. The warning for this exact failure already exists, and status does not print it

`monitor/ops.py` has a function whose whole job is to say the scheduler was left alone and how
old it is. Its docstring names the precedent in plain words:

> Printing nothing here is what let 21 backend restarts read as full restarts while a scheduler
> from three days earlier kept running a cron table that no longer matched the code. Age is the
> number that exposes it.

That is this failure, described before it happened again. The function is called from exactly one
place — the restart path. **`ops.py status` never calls it.** So the read-only command an operator
runs to check health is the one command that does not tell them the schedule in memory no longer
matches the schedule on disk. The line exists; it appears only once you are already restarting,
which is after the moment it would have helped.

Recorded rather than repaired: this stage is a read-only precheck, and `status` is the
instrument the operator reads. Changing an instrument during a measurement is the wrong order.
The repair is one call and belongs to whoever next touches that file.

## 10. Regression, classified

```text
before Stage 5ZX repairs   109 failed / 2460 passed
after  Stage 5ZX repairs    99 failed / 2470 passed
after  this precheck        95 failed / 2476 passed / 5 skipped   = 2576 collected
```

The last line reconciles against a collect-only count, which is the check worth doing: totals
that nearly agree are how a miscount survives. Two more tests exist than before — the scheduler
wiring test, and one new parametrised case created by declaring the dashboard row.

Four failures went away and **three of them are repairs made here**. The fourth is a browser
assertion about a tooltip, in a file this work does not touch; it passes in isolation, and it is
counted as the corpus's known order dependence rather than credited as a fix. Claiming four would
have been the easy arithmetic and the wrong one.

**Nothing went red** — established by diffing the two failure lists rather than by comparing
totals, because a total can stay flat while one test is traded for another.

| bucket | count | what they are |
|---|---|---|
| caused by the Calm slot split | **45** | measured, not read off the names: the same failures re-run with the pre-stage slot table restored turned 45 green. Slot count pins (`70`, `101`, `130`), per-sleeve counters, and 16 tests that drive `TRACK1_CALM_1000` by name |
| pre-existing, unrelated | ~51 | blocker-roster pins, a legacy count of 61 against a pinned 60, absence proxies asserting the live runtime tree does not exist on a machine where the route has been running for days, date pins |
| **true Stage 5ZX regressions** | ~~3~~ **4** | the dashboard fact pin, two cases behind the argv extractor, and — **corrected in Stage 5ZZ** — a third copy of that extractor in the ops-startup suite. **All four repaired** |

**Corrected after the fact, in Stage 5ZZ.** The fourth regression was missed here because this
classification grouped failures by their message text, and that one failed with different
wording — `_track1_body argv not found` rather than `no _run([...]) call found` — so it landed in
the pre-existing bucket. Grouping by symptom is faster than reading each failure and it put a
genuine regression in the wrong pile.

It matters more than the arithmetic: that test asserts **no order flag can reach a Track 1
slot**, and it had stopped running. Corrected split: **45 / ~50 / 4**.

The corpus also has about ten per cent of noise in any count taken from it: the same set of tests
run twice produced 109 failures and then 98. Eleven of them pass or fail depending on what ran
before them. That belongs to the corpus, not to this work, but anyone treating a failure count
here as a threshold should know it first.

**The 45 are left red and listed rather than repaired.** The count pins are the roster
anti-pattern already on this project's record, and the ones that drive the old slot exercise
ten-o'clock semantics that no longer exist — repairing those means deciding, test by test, what
the new Calm timing should mean, and doing that quietly inside a precheck is how an assertion gets
weakened without anyone choosing to weaken it.

## 11. What is still blocked before paper

| | |
|---|---|
| **the scheduler restart** | **new, and it is now the first thing.** Until it happens the two jobs exist only in the code and the Calm window loses even its refusal row |
| `PAPER_SHADOW_EVIDENCE` | 3 judgeable days of 5, and **0 carry Calm evidence**. All three are FAIL days in any case, so the count that matters is closer to zero than to three |
| `B1` | no decision recorded; the measurement backing it **expires 2026-08-27 11:34 ET** and will need re-running on the day the decision is made |
| the SEND wire | does not exist, and nothing here builds it |
| machine sleep | operator; unchanged |
