# Stage 5ZU — Calm A was waiting for a bar that cannot exist while it is allowed to look

**2026-08-26, ET 11:45–13:10.** No orders · no confirmation file · no broker connection ·
**nothing restarted** · no runtime evidence written · splice guard untouched · the entry price
definition unchanged and asserted.

```text
UTC 2026-08-26 17:10 · ET 2026-08-26 13:10 EDT · Calgary 2026-08-26 11:10 MDT
```

---

## Verdict

| | |
|---|---|
| backtest contract | **CONFIRMED** — 421 of 421 rows |
| live gate mismatch | **CONFIRMED** — four minutes, every day |
| fix applied | **yes**, in the gate *and* at the call site |
| Calm can become judgeable | **yes in the gate — not yet in the schedule** (§6) |
| strategy changed | **no** — the entry is still the OPEN at 10:00, asserted |
| splice guard unchanged | **yes** |
| orders possible | **false** |
| remaining blockers | three, unchanged |

---

## 1. The contract, on all 421 rows

```text
421 rows   MNQ 217 · MES 204   LONG only
           IS_2018_2024 349 · OOS_2025 44 · SANITY_2026 28
```

| claim | result |
|---|---|
| `signal_time <= entry_time` | **PASS**, 0 violations |
| `signal_after_entry == 0` | **PASS** |
| `outside_entry_bar == 0` / `outside_exit_bar == 0` | **PASS** |
| signal at 09:30:00 · entry at 10:00:00 · exit at 15:55:00 | **PASS** on every row |
| entry − signal | **exactly 30 minutes — one distinct value across the whole file** |

That last line is the whole stage in one number. **The decision is fixed half an hour before
the bar the live gate was waiting for.**

### The prices, and why only one window matches

| window | rows | entry equals the 10:00 OPEN exactly | largest offset |
|---|---:|---:|---:|
| SANITY_2026 | 28 | **28** | 0.00 |
| OOS_2025 | 44 | 0 | 535.75 |
| IS_2018_2024 | 349 | 0 | 1548.43 |

The series is a **back-adjusted continuous contract**: every roll subtracts a gap from all
prior history, so the older a row is the larger the accumulated adjustment. Three independent
signs, none of which relies on believing the explanation:

- the offsets are **monotone in age**, with about fifty distinct levels — not one constant and
  not noise;
- **395 of 416 rows have an identical `exit − entry`** — an additive offset cancels in a
  difference, so the artifact and the parquet are describing the same two bars;
- `prev_close_loc`, which is **offset-invariant**, agrees far more often than the ratio
  features, which are not.

So the contract is confirmed, the current window reproduces to the cent, and the older rows'
absolute level is not reproducible from today's parquet **by design**. The existing 421-row
reproduction test still passes because it checks the window whose prices are still current.

### A measurement error of mine, and the thing that caught it

The first run used the module's `_naive()`, which **strips** a timezone without converting it.
The parquet index is **UTC** — `track1_live_source.frozen_frame` says so, in a comment written
after an earlier incident. Every bar came back four or five hours off and 420 of 421 entries
mismatched.

What gave it away was not the count. It was that the parquet returned `9184.872880047082`
where the artifact said `8753`. **A price that cannot be a tick is a fault in the measurement,
not in the data.** Re-run through the route's own loader, the numbers became the ones above.

## 2. The contradiction

```text
decide_from / decide_to     10:00 / 10:00   + 60s grace  ->  deadline 10:01:00
decision_bar                10:00, and it had to be a CLOSED five-minute bar
a closed 10:00 5m bar       first exists at                    10:05:00
```

Four minutes apart. Reproduced from the requirement table with the same two codes and the same
wording the live slot emitted: *"last bar in the span is 09:55, expected 10:00"* and *"no bar
at 10:00; its OPEN is the entry price"*.

**Calm was the only sleeve whose decision bar was also the first instant it was allowed to
decide** — asserted by a test derived from the table rather than written about it.

| sleeve | why it escapes |
|---|---|
| `roska4_stress` | `today_to` 10:30 sits **before** `decide_from` 10:35 — its level is always already closed |
| `roska4_swing`, `global_nkd` | `today_to_follows_now=True` — Stage 5V-1 fixed this exact class after nineteen consecutive NKD slots refused `partial_coverage` |

Calm kept `False` deliberately, because for Calm `today_to` really is a bar the trade
transacts at. That was right about the *price* and wrong about the *decision*.

## 3. The fix: two names where one was doing both jobs

```text
required_context_through   09:55   the last bar the DECISION reads
required_entry_quote_time  10:00   the bar whose OPEN is the fill reference
```

The rule reads the prior RTH session and today's 09:30 open. Nothing else. The 10:00 bar
contributes exactly one thing — the OPEN the entry transacts at — and that is now declared as
what it is and checked against the **minute** index it is actually read from, not against the
five-minute decision frame. Two bar sizes, two questions; conflating them is what made the
sleeve impossible.

`decision_bar` is retired for Calm, and a test fails if it comes back.

Two new refusals, kept apart on purpose:

```text
entry_quote_absent      the fill reference is not readable yet
entry_quote_unverified  no index was offered, so that half was NOT checked
```

The second is never reported as a pass. A check that did not run is not a check that passed.

**The grace moves from 60s to 180s, and that is an observation change, not a strategy one.** A
one-minute bar stamped 10:00 closes at 10:01:00, so sixty seconds put the deadline exactly on
the closing instant. Three minutes let a slot observe a **closed** bar and still refuse
anything past 10:03. The entry price is asserted equal to `CalmAParams.entry_time` — 10:00,
unchanged.

### The gate change alone did nothing

The slot passed only the resampled five-minute frame, so every Calm slot would have refused
`entry_quote_unverified` instead of `decision_bar_absent` — **a different refusal, not a fix.**
The regression caught it: a live-source test stopped reaching `decided`.

The joined one-minute frame was already in scope at the call site, three lines above. It is now
passed as the quote index.

## 4. The partial-bar constraint holds by construction

Measured live today at 10:00:19: **MNQ's joined frame already carried a bar stamped 10:00** —
nineteen seconds of one — while MES's stopped at 09:59. A partial bar's OPEN is final from its
first tick; its high, low and close are not.

The context span stops at **09:55**, so a 10:00 bar in the frame is outside everything the
decision reads. Proved by verdict equality rather than by argument: adding a partial 10:00 bar
with an absurd high of 99 and low of −99 changes neither the verdict, nor the codes, nor the
span detail.

## 5. The four outcomes, exercised

```text
last closed 5m 09:55, no quote index offered      ->  REFUSE  entry_quote_unverified
last closed 5m 09:55, minutes only to 09:59       ->  REFUSE  entry_quote_absent
last closed 5m 09:55, minute 10:00 closed, 10:01  ->  ALLOW
at 10:03:30, past the grace                       ->  REFUSE  too_late
a hole at 09:45                                   ->  REFUSE  gap_in_coverage
```

No-late-entry survives. A refused slot is `SLOT_REFUSED`, never `NO_SIGNAL` — those are
different facts and only one of them is about the market.

## 6. What the fix does **not** do, and this is the honest part

**Calm will still refuse tomorrow at 10:00.** The slot is dispatched at 10:00:00 and the quote
it needs closes at 10:01:00. Today at 10:00:19 one instrument had a partial 10:00 bar and the
other had nothing; the sleeve takes the first instrument's index, so it would refuse
`entry_quote_absent` — a correct refusal for a real reason, which is an improvement on a
refusal for an impossible one, but still not a PASS.

**What would fix it: dispatch the Calm slot at 10:01 or 10:02.** The entry price is unchanged,
so this is an observation-time change and not a strategy change. It is a scheduler cron edit
and needs a restart, so it is **recommended here and not applied**.

Until then `PAPER_SHADOW_EVIDENCE` cannot count a Calm PASS, and that gate requires every
sleeve to pass at least once.

## 7. Tests

**33 tests.** Mutation sweep **11 of 11 red**, including all five the stage names: requiring a
closed 10:00 bar again, using the 10:00 high in the setup, allowing a late 10:05 entry,
treating a missing quote as a pass, and moving the entry off the 10:00 open.

**Five older tests were updated, not weakened.** They pinned the old contract and called the
gate for Calm without saying where the entry quote comes from. One became **stronger**: the 3B
parametrised case now separates *"the quote index was not offered"* from *"it was offered and
the bar is absent"* — two facts the single old code could not tell apart. One test was added.

**Regression: 307 passed, 1 failed, 3 skipped.** The one is a roster pin expecting the old
blocker list, measured pre-existing during the Stage 5ZQ bisect.

## 8. Stage 5ZT, closed here

5ZT's four deliverables were never written: its two decisive events were still in the future
when the next stage arrived. They have since happened, and leaving them unanswered would be
worse than recording them out of order.

```text
12:30:25 ET   the stress window closed and wrote BOTH the book and the checkpoint
book after    schema_version 2, route track1_candidate
checkpoint    written for the first time since 02:55
```

**The repaired envelope survived a real window close.** Carry-forward accepted it, with no
refusal and no schema or route mismatch, and `live_positions.json` sat untouched at 09:31:11
throughout. Orders remained impossible.

## 9. Remaining before paper

| | item | class |
|---|---|---|
| 1 | the B1 decision — and the state of the world that makes it true | operator |
| 2 | five clean judgeable shadow days — **and Calm cannot contribute one until its slot moves** | time + one cron edit |
| 3 | the regime gate's first PASS | time |
| 4 | machine sleep | operator |
| 5 | **the order path** — `run_live_day_track1` constructs `NoOrderBroker` and never `IBKRBroker` | code, unwritten |

### For the operator

```powershell
# the one change that makes Calm judgeable — a cron edit, then a restart
#   track1_calm_1000  10:00  ->  10:01
# the entry price stays the 10:00 OPEN; only the moment of observation moves.
```

## 10. The wider regression, and which of it was mine

The full `scratch/` sweep came back **2461 passed, 48 failed**. Measured rather than
attributed by eye: the two source edits were reverted in a subprocess and the twenty affected
suites re-run.

```text
with Stage 5ZU      46 distinct failing tests
without Stage 5ZU   33
caused by 5ZU       13    — all thirteen now fixed
```

### The grace group — nine tests, and the pin was a coincidence

Stage 5ZB asserted `decision_grace_seconds == 60` on **every** sleeve, and that 61 and 120
seconds late are refused. Calm's grace is now 180 on purpose, so those went red.

They are rewritten to read the grace **per sleeve, from the requirement**, and to assert that
the one sleeve which differs is the one with an entry quote to wait for. That is a stronger
claim than the uniform number: the old test would have gone red the first time any sleeve
needed its own grace, for a reason that had nothing to do with lateness.

The boundary test now derives both sides from the declared value, so it moves with the
requirement and still fails if the boundary disappears altogether.

### The calm gate group — four tests

4B, 4C and 5ZA called the gate for Calm without saying where the entry quote comes from, and
got `entry_quote_unverified` — the correct new answer to a question they had not asked. Each
now offers the minute index.

One needed more than wiring. 4B's second half asserted `decision_bar_absent`, a code Calm no
longer emits. Its frame stops short of the **decision** span, so it now asserts that refusal —
the same claim, in the terms the contract uses.

### And a helper of mine that overflowed

Deriving "one second past the grace" as `_slot_now(slot, seconds=grace + 1)` built the
timestamp by formatting the seconds field, so 181 became `10:00:181` and the test died on a
parse error rather than an assertion. Fixed with a `Timedelta`. Worth recording only because
the failure looked like a contract problem and was not.

**After the repairs: mutations 11 of 11 still red, and the 33 pre-existing failures are the
families measured during the Stage 5ZQ bisect — roster pins, absence proxies, slot-count
pins — none of them mine.**

### After every repair

```text
2476 passed, 35 failed, 5 skipped     (was 2461 / 48)
none of the thirteen remain
```

Thirty-five rather than the bisected thirty-three because the full sweep runs sixty-seven
suites against the bisect's twenty, and this repo has measured order-dependent failures
before — fifteen of them in the Stage 5ZQ sweep.

One was spot-checked because it touches the book and this session changed the book:
`test_8c_persisting_the_book_writes_the_route_path_and_never_legacy` asserts
`live_positions.track1.json` does not exist. The live system wrote it at 12:30:25 today. It is
an **absence proxy**, stale since Stage 5ZN gave the route a cross-day book — the same family
as the others, and neither 5ZS's nor this stage's doing. Its failure message blames the test's
own redirection, which is exactly what an absence proxy looks like once the world moves under
it.

