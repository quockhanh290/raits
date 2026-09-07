# Track 1 switch-over runbook

**What this is for:** the ordered steps that turn the legacy route off and Track 1 on, so that
exactly one route ever holds a position in a given IBKR login.

**What it is not:** a decision. Nothing in this document may be executed until the project
owner records the choice in `track1_go_live_confirmation.json`. Until then
`global_index/track1_gates.py` refuses to arm the Track 1 order gate, and that refusal is code,
not a reminder.

---

## 0. The constraint this whole document exists for

`IBKRBroker.__init__` takes `host`, `port`, `client_id`, `bar_duration` and nothing else.
`get_positions()` reads `ib.positions()` unfiltered; `get_equity()` reads `NetLiquidation`
unfiltered. So **one IB Gateway login is one position book**, and two routes holding the same
four symbols do not coexist as two books — they coexist as one net signed quantity per
contract that no reconcile can decompose.

Concretely: legacy LONG 1 MNQ beside Track 1 SHORT 1 MNQ reconciles as broker × 0 against two
file rows. That is `B3 MISMATCH`, and it halts entries for **both** routes. It is the same
mechanism that put the legacy `STRESS_MID` cron behind `if False:`.

`client_id` does not solve this. It decides who may cancel an order, not whose positions are
counted.

**So there are exactly two ways forward, and they are mutually exclusive:**

| | what it means | confirmation flag |
|---|---|---|
| **A — retire legacy first** | legacy stops trading; Track 1 becomes the sole route on the existing account | `legacy_retired_confirmed` |
| **B — a second account** | Track 1 runs on its own IBKR login while legacy keeps running | `separate_account_confirmed` |

Path A is the stated end state and the cheaper of the two. Path B costs a second account, a
second Gateway, and a second set of every state file — and it makes both routes' `B3` reconcile
meaningful only if the accounts genuinely never overlap.

The rest of this runbook is written for **path A**.

---

## 1. Preconditions — all of these before anything is turned off

Every one is checkable, and none of them is "we think so".

| # | precondition | how to check |
|---|---|---|
| 1 | Every Track 1 blocker is `CLOSED` or has its confirmation on file | `python -c "from global_index import track1_gates as g; print(g.may_enable_orders(g.load_confirmations()[0]))"` |
| 2a | Every sleeve's generator is promoted, and its readiness metadata is green | `global_index/track1_live_sleeves.readiness()` reports an empty `blocked` list |
| 2b | Track 1 actually produces a live decision | `track1_sleeves.load_source("live-shadow").candidates(<slot instant>)` returns a list for **both** windows |
| 3 | Track 1 slots exist in the scheduler **and** in the dashboard mirror | `track1_slots.parity_report()["in_parity"]` is true with Track 1 rows on both sides |
| 4 | No stop-repair sweep lands inside the Track 1 Stress window | build the scheduler both ways and compare — see **"How to check 4"** below |
| 5 | Track 1 has run shadow for a measured period with the window ledger on | `window_coverage_*.jsonl` shows `complete` for both windows on every trading day of that period |
| 6 | The Track 1 checkpoint is bootstrapped under `track1_params` | `track1_bootstrap.accepts(...)` returns `Resumed`, not a `Refusal` |
| 7 | Legacy is flat — **at the broker**, not only on disk | `live_positions.json` has `positions: []` **and** IBKR reports no position **and** no working STP remains |
| 8 | The route can build today's frame, and only through the guard | `python -c "from global_index import track1_gates as g; print(g.live_frame_wiring())"` reports released |

### Where each precondition actually stands (audited 2026-08-23, read-only)

Four of these are met today and four are not. The four that are not cannot be met by reading
anything — they need a shadow scheduler to have run, or a broker to have been asked.

| # | today | what moves it |
|---|---|---|
| 1 | **FAIL by design** | the B1 decision below. Nothing else blocks the order gate. |
| 2a | **PASS** | already met — all four generators are promoted |
| 2b | **CLOSED OFFLINE** | both slotted sleeves answer; the broker provider is still untested |
| 3 | **PASS** | — |
| 4 | **PASS** | — |
| 5 | **FAIL** | finish 2b, THEN run the shadow scheduler. Wiring landed in Stage 5D; the live source has not. |
| 6 | **FAIL** | the first window that actually COMPLETES; an incomplete window writes no checkpoint, on purpose |
| 7 | **PARTIAL** | the file half is met; the broker half has never been asked |
| 8 | **PASS** | — |

**Preconditions 5 and 6 are EXPECTED to fail before the first shadow run**, and until Stage 5D
they could not be fixed by starting either.

> **Correction (Stage 5D).** An earlier version of this paragraph said "starting is what fixes
> them". That was wrong, and it was wrong in the way this project keeps getting caught: it was
> reasoned from how the route was meant to work, never checked against the call sites. Measured,
> the Track 1 slots passed only `--regime-csv`, so the entry point took its defaults —
> `--source replay --window vault2026` — and each of the Track 1 slots re-ran the same measured
> window from months ago. `record_window_observation` and `track1_bootstrap.write` both had
> **zero callers**. Starting the scheduler would have produced no coverage and no checkpoint, at
> any length of run.

Stage 5D wired the missing half: the slots now pass `--source live-shadow --sleeve <s>
--slot-id <id>`, each slot writes its own ledger row, and the last slot of a window closes it
and writes the checkpoint — but **only if the window actually completed**.

**What still holds them shut is precondition 2b, not the wiring.** A slot counts toward
coverage only when it DECIDED, and while the live candidate source raises, every slot records
`decided=false, reason=live_source_not_ready`, the window closes `incomplete`, and no checkpoint
is written. That is deliberate: counting an undecidable slot as observed would manufacture
exactly the evidence the ledger exists to withhold, and would let precondition 5 go green on a
route that cannot trade.

So the order is: finish 2b → then run the shadow scheduler → then 5 and 6 turn green on their
own. Starting before 2b collects nothing but rows saying it collected nothing.

**And the ledger must be switched on.** `RAITS_WINDOW_LEDGER_DIR` unset means the ledger writes
nothing at all; for legacy that is a deliberate no-op, and for a Track 1 live-shadow slot it is
now a hard refusal — the slot stops rather than running silently, because a shadow run whose
purpose is to leave evidence must not succeed quietly when it cannot.

**Precondition 2 is split for a reason.** `readiness()` returning an empty `blocked` list means
every sleeve's generator has been promoted into the package and reproduces its committed rows.
It does **not** mean a live decision can be taken.

**Where 2b stands after Stage 5E — partial, and the halves matter.**

Only two sleeves have a Track 1 slot at all: Calm A at 10:00 and Stress between 10:35 and 12:30.
`roska4_swing` and `global_nkd` decide in the afternoon and overnight, and have no slot, no
intraday requirement and no ledger window — a live source cannot be asked for them, and asking
is a named refusal rather than an empty list.

Of those two, **both now answer**:

| | state | what it means |
|---|---|---|
| **Calm A, 10:00** | **closed offline** (Stage 5E) | candidates with a causal D-1 regime label, an explicit cost object, and risk from the ACTUAL disaster-stop distance |
| **Stress, 10:35–12:30** | **closed offline** (Stage 5F) | the `mnq_only_g3_q7` rule promoted into `global_index/track1_stress_mnq.py`, reproducing the scratch chain EXACTLY on all three windows — 4, 3 and 50 trades, every field identical, P&L delta $0.000000 |

**"Closed offline" is the whole caveat, and it is the only thing standing in 2b's way now.**
Every test injects `FrameBarProvider`. **No broker provider has been constructed, let alone
connected**, so nothing here says a live feed produces these candidates — only that both rules,
the label, the costs and the risks are computable from bars, and that the plumbing carries them
into the ledger and the checkpoint.

The honest statement is "both windows are answerable offline".
It is never "Track 1 can trade today".

**And the risk is the true stop distance, not a multiple.** Calm A's candidates carry
`risk_dollars = abs(entry - disaster_stop) x point_value x qty`, where the stop is
`entry - 1.5 x ATR` and the ATR is the last daily value **strictly before** today. The measured
artifacts size from `asof(day)`, which takes today's own row when it exists — defensible in a
backtest that books the whole session at once, and lookahead at 10:00. So a live risk figure can
differ slightly from the artifact's for the same day, in the causal direction.

### How to check 4

`_ENTRY_WINDOWS` is a **local variable inside `make_scheduler`**, not a module attribute, so any
check that names it directly raises `AttributeError`. Check the effect instead — build the
scheduler both ways without starting it:

```python
from global_index import run_scheduler as rs, track1_slots as ts
off = {j.id for j in rs.make_scheduler(port=4002, dry_run=True, track1_shadow=False).get_jobs()}
on  = {j.id for j in rs.make_scheduler(port=4002, dry_run=True, track1_shadow=True ).get_jobs()}

assert "stop_repair_1220" in off                  # legacy keeps its 12:20 sweep
assert "stop_repair_1220" not in on               # Track 1 mode drops it
assert off - on == {"stop_repair_1220"}           # and drops nothing else
assert len([i for i in on if i.startswith("track1_stress_")]) == 24   # 10:35..12:30 by 5
assert "track1_stress_1035" in on and "track1_stress_1230" in on
assert ts.REQUIRED_ENTRY_WINDOW == rs._TRACK1_STRESS_WINDOW
```

and the dashboard mirror, which keys on its own copy of the same window:

```python
import os, importlib, monitor.backend.schedule_status as ss
for flag in ("0", "1"):
    os.environ["RAITS_TRACK1_SHADOW"] = flag
    importlib.reload(ss)
    assert ss.TRACK1_STRESS_WINDOW == ts.REQUIRED_ENTRY_WINDOW
    assert ts.parity_report(track1_shadow=(flag == "1"))["in_parity"]
```

`make_scheduler` builds and registers jobs; it does **not** start anything and opens no
connection. Both of these are safe to run on a live machine.

### Precondition 7 is two checks, and only one of them is local

`live_positions.json` showing `positions: []` says this system's book is empty. It says nothing
about the account. The broker may hold positions this system never opened, and it may hold
**working stop orders with no position behind them** — which is what step S3 exists for, because
such an order fills into a position nobody asked for.

**Legacy is not flat until IBKR has been asked.** No audit that forbids connecting can answer
it, and none has: as of 2026-08-23 the broker half and the orphan-stop check have never been
run. Do not let a clean local file stand in for either.

**Precondition 8 was added in Stage 4B, when it could not be met, and Stage 4C met it.** The
route now has exactly one place where live bars arrive, and every path out of it ends in the
checked join — including the paths where nothing new arrived, which is where an unchecked frame
would otherwise slip through. The check above answers released today.

Two things about it are worth knowing before relying on it. First, it is **measured, not
signed**: it re-runs on every read, and a fetch added later that skips the join shuts this
precondition again on its own. Second, the conversion between the two clocks — history is UTC
read as New York, Tokyo for the Nikkei sleeve; the broker path returns naive ET — is the step
that once let live Nikkei bars overwrite 1,050 of 1,590 frozen bars. It is now explicit, it
happens in one place, and errors in both directions are refused: a session landing back on
history is caught by comparing prices where the two halves overlap, and a session landing past
history is caught because no bar may be stamped after the moment it was fetched at.

What precondition 8 does **not** say is that a live day has been run. None has, and no broker
has been connected.

> **Correction (Stage 5H, measured 2026-08-23).** It also does not say the slot can obtain bars,
> and today it cannot. `main()`'s `live-shadow` branch calls `observe_live_slot(...)` **without a
> provider**, and there is no `--bar-provider` flag, so the factory Stage 5G moved into
> `track1_live_source.build_bar_provider` has no caller on the scheduler path.
>
> Running the exact command a Track 1 slot issues, with a temporary ledger directory, produces:
>
> ```
> slot TRACK1_CALM_1000 seq=0  decided=False  reason=no_bar_provider
> window closed: 0 of 1 decided (1 slots ran)
> checkpoint: NOT written — the window did not complete
> ```
>
> So starting the shadow scheduler today writes ledger rows that faithfully record that nothing
> **Superseded by Stage 5I (2026-08-23).** The selector now exists and the slot is wired:
>
> - `--bar-provider {none,ibkr}` is parsed and used; the default is `none`, so a manual run
>   still cannot open IBKR by accident, and the scheduler slots pass `ibkr`.
> - The broker is released in a `finally`, and the ledger check runs **before** a broker is
>   built — a slot that could not record its run does not open a connection to find out.
> - Track 1 ledger rows now carry `route=track1_candidate` on `window_open`, `slot_observed`
>   and `window_closed`. They were being stamped `legacy`, which filed Track 1's coverage under
>   the route it exists to replace. Legacy children still stamp `legacy`.
> - **The slot now runs the route's own decision machinery**: the freshness gate, the cap guard,
>   the admission layer and the explanation writer — the same four the replay path uses. Before
>   this, a shadow day would have recorded decisions that had passed no cap and no freshness
>   gate, and left no audit trail.
> - Because the mode is `shadow_live`, freshness **binds**: if the gate refuses while the route
>   admitted a candidate, the slot records `freshness_refused` and the window stays incomplete
>   rather than counting toward coverage.
>
> **So a shadow day now collects route-level evidence, not detection-only evidence.** What is
> still untested is the broker provider itself — every test injects a fake, and no IBKR
> connection has ever been made.

> was collected. Preconditions 5 and 6 stay shut, correctly. **A `--bar-provider` selector wiring
> `build_bar_provider` into the live-shadow branch is the one remaining piece before a shadow
> period collects anything.** That is code, not an operator step, and it is not done.

Precondition 7 is the one that cannot be rushed. Legacy holds swing positions for up to five
days and NKD for up to five sessions. Switching over while legacy holds anything means the new
route inherits positions it has no book for.

---

## 2. Before any of this: two things that come first

### S0a — find out why the scheduler is down

As of **2026-08-23 the scheduler is not running**: no `run_scheduler` process, and `runner.pid`
is absent. It *was* running days earlier. Nothing in the Stage 4/5 audits started or stopped it,
and no record says who did or why.

**Establish that before starting anything.** The two possibilities lead opposite ways:

- **Deliberate** — someone began winding legacy down. Then the drain below is partly done and
  the steps continue from S1.
- **Accidental** — the system has been silently not trading since **2026-08-21**, which is an
  operational incident in its own right and wants handling before a route switch is layered on
  top of it.

A related clock is already running: nothing refreshes `spy_daily_live.csv` while the scheduler
is down. It was one business day stale on 2026-08-23, which is clean, but past **five** business
days the G1 hard gate blocks new entries on **both** routes.

### S0b — `STOP_TRADING` goes in before ANY scheduler start

Not before S5. Before the first start of any kind, including a shadow-only one.

**`--track1-shadow` adds Track 1's jobs. It does not remove legacy's.** Measured:

| | jobs | Track 1 slots | legacy jobs | legacy `live_day` entry slots |
|---|---|---|---|---|
| shadow OFF | 60 | 0 | 60 | 23 |
| shadow ON | 84 | 25 | **59** | **23** |

Turning shadow on adds every Track 1 slot and removes exactly one — `stop_repair_1220`.
(The count was written as 25 here until Stage 5M-B added the 23 Normal-R4 slots; it is
deliberately not restated, because the table in `track1_slots.TRACK1_SLOTS` is the one
place it should live.) Every legacy entry
slot is still registered and will still fire.

So **starting the scheduler in shadow mode resumes legacy trading.** If the intent is to retire
legacy, the kill switch must already be on disk when that start happens; otherwise the first
thing the new configuration does is take legacy entries, which is the opposite of the intent and
happens without anyone deciding it.

The order is therefore: **`STOP_TRADING` → start scheduler → watch → everything below.**

---

## 3. Switch-over, in order

Each step says what to check before moving on. A step whose check fails is a stop, not a
warning.

**S1 — freeze legacy entries, keep its exits.**
Create the legacy kill switch: an empty file named `STOP_TRADING` at the repo root. Legacy's
D5 gate clears `entry_candidates` on every run and leaves exits untouched. The gate is real and
wired: `run_live_day.py` passes `--stop-path` (defaulting to that name) into the runner, and
the runner empties `entry_candidates` when the file is present while exits run normally.
*Check:* the next `live_day_*.log` contains `D5: STOP_FILE present`.
*Do not* stop the scheduler here. Legacy's open positions still need their exits, their stop
repair sweeps and their max-hold job.

**This step is S0b when the scheduler is down.** If the scheduler is not currently running —
which it is not, as of 2026-08-23 — then this file must exist *before* it is started, not after.
See section 2. Starting a scheduler with Track 1 shadow on while `STOP_TRADING` is absent
re-arms 23 legacy entry slots.

**S2 — let legacy drain.**
Wait until every legacy position has exited by its own rule. Up to five trading days.
*Check:* `live_positions.json` shows `positions: []`, and IBKR shows no position on
MES/MNQ/MYM/M2K/MNK. Check both — the file and the broker — because agreeing is the point.

**S3 — cancel every working stop that belonged to legacy.**
*Check:* `python -m global_index.check_open_orders` reports no working STP.
A stop left working with no position behind it fills into a position nobody asked for.

> **Neither S2's broker half nor S3 has ever been run.** Every audit through Stage 5B was
> forbidden from connecting, so both remain genuinely unknown rather than assumed good. The
> local book has been flat since 2026-08-21 and the account's last-seen net liquidation was far
> larger than this system's equity, so the account plainly holds more than this system's
> positions. Read any broker screen with that in mind: "no position" must mean no position **on
> MES / MNQ / MYM / M2K / MNK**, not an empty account.

**S4 — record the confirmation.**

> **Do not write this file yet.** It is the last thing to create, not the first. Every check
> above it must have passed first — the broker reporting flat (S2), no working STP left (S3),
> and an operator who has decided. The file is what arms a route; writing it early arms one
> whose preconditions nobody finished checking.

Write `track1_go_live_confirmation.json`:

```json
{
  "schema_version": 1,
  "confirmed_by": "<name>",
  "confirmed_at": "<YYYY-MM-DD>",
  "legacy_retired_confirmed": true,
  "note": "<why, in one sentence>"
}
```

For path B, replace `legacy_retired_confirmed` with `separate_account_confirmed`. Those two are
the **only** flags the schema accepts; `note` is optional, the other three keys are required.

**An earlier version of this template did not work.** It listed `scheduler_wiring_approved`,
`normal_generator_isolation_accepted` and `calm_a_detector_accepted_frozen` — flags that were
removed in Stage 4 when the blockers they released were closed. Because the file is refused
*whole* on any unknown key, copying that template granted **zero** flags: the gate stayed shut
and looked like a code fault, at the one moment when an operator is least able to debug it. A
flag that releases nothing is worse than no flag, which is why they were deleted rather than
left in place.

The file is schema-checked on every read. An unknown key, a non-boolean flag, a wrong
`schema_version`, a missing `confirmed_by` — any of those refuses the whole file rather than
honouring the parts that parsed.
*Check:* `load_confirmations()` returns no errors and the flags you intended:

```python
from global_index import track1_gates as g
conf, errs = g.load_confirmations()
assert errs == [], errs
assert conf.get("legacy_retired_confirmed")
```

**S5 — remove legacy's jobs from the scheduler, add Track 1's.**
One change, both halves, plus the `schedule_status.py` mirror in the same commit.
*Check:* `track1_slots.parity_report()["in_parity"]` is true.

**S6 — restart the scheduler.**
*Check:* the startup banner lists the expected job count, and `stale_code` in
`/api/v1/schedule-status` is false.

**S7 — arm Track 1.**
`TRACK1_ORDERS_APPROVED=1` in the scheduler's environment, and `--allow-orders` on the Track 1
entry point.
*Check:* the entry point prints `mode: armed`. If it prints `armed_but_refused`, read the
reasons — every one names a blocker or a confirmation problem.

**S8 — first live day, watched.**
*Check, before the first entry:* `live_positions.track1.json` is being written, the window
ledger reports `complete`, and the dashboard shows the Track 1 route.
---

## 3b. Where Track 1 writes — scratch is not the operational store

**Added by Stage 5K0 (2026-08-23).** Two roots, and the difference matters the first time
someone tidies up:

| root | holds | why there |
|---|---|---|
| `scratch/track1_shadow/` | **replay and test** output — decisions, settlements, summaries | research output, reproducible from the measured windows; losing it costs a re-run |
| `global_index/track1_runtime/` | **live-shadow operational evidence** — `window_coverage/`, `slot_timing/`, `shadow/explanations/` | **not reproducible.** Nobody can re-observe a window that has closed, and this is what the go-live gate is read from |

Before Stage 5K0 the live-shadow explanations defaulted to `scratch/track1_shadow` and the
operator runbook pointed `RAITS_WINDOW_LEDGER_DIR` at `scratch/track1_ledger`. A multi-day shadow
period would have kept its only copy inside the directory this project sweeps.

`global_index/track1_runtime/` sits beside the route runtime state already kept there —
`live_state_data.js`, `preflight_state.json`, `replay_checkpoint.track1.json` — rather than
inventing a new top-level directory.

The explanation writer still refuses anything outside those two roots. Widening it to a **set**
did not widen it to the tree: `global_index/`, `scratch/`, `monitor/backend` and a bare filename
are all still refused, and there is a test for each.

**Ignored, all of it.** `live_positions.track1.json`, `runner.track1.pid`,
`replay_checkpoint.track1.json`, `STOP_TRADING.track1`, `track1_go_live_confirmation.json` and
`global_index/track1_runtime/` are in `.gitignore`. Their legacy counterparts already were; the
Track 1 twins were not, so a shadow run would have offered route state for commit — and the
confirmation file is the one that ARMS the route, so a checkout must never be able to create one.

---


---

## 4. Rollback

Track 1 is not yet proven. Rolling back must be as ordinary as rolling forward.

1. Remove `TRACK1_ORDERS_APPROVED` from the environment and create `STOP_TRADING.track1`.
   Track 1 stops taking entries; its exits continue.
2. Let Track 1 drain, exactly as S2 did for legacy. Same check: file and broker agree.
3. Cancel any working Track 1 stop.
4. Delete `track1_go_live_confirmation.json`. The gate closes again by itself — nothing else
   has to be remembered.
5. Restore legacy's jobs and remove `STOP_TRADING`.

**The two routes must never both be armed.** There is no code that enforces this across a
scheduler restart, and that is the honest state: the enforcement is this document and the
confirmation file, not a lock. If both were armed on one account, the first B3 reconcile would
halt both — loudly, which is the better failure, but a failure.

---

## 5. What this runbook deliberately does not do

* It does not delete legacy code. Legacy stays readable and re-startable until Track 1 has a
  measured live record.
* It does not touch `configs/final_params.yaml`, the frozen parquet, or the vault baseline.
* It does not migrate legacy's history into Track 1's book. The two ledgers have different
  epochs and merging them would produce a P&L series that never happened.

---

## 6. The 13:45 pre-flight is SHARED infrastructure — retiring legacy must not retire it

*Added 2026-08-23 (Stage 5L). Correction to the reading this document invited earlier: the
pre-flight was described alongside the legacy slots, and that put it on the wrong side of the
line.*

### What it is

One job, 13:45 ET Mon–Fri. It refreshes the futures parquet store (`update_ibkr_daily`) and
the regime CSV (`update_spy_csv`), and it writes the only record anywhere that either of them
ran (`global_index/preflight_state.json`).

It decides no trade. It belongs to neither route. **Both routes read it:**

| Reader | What it reads | When |
|---|---|---|
| legacy 14:05–15:55 slots | the in-memory flag for today | after 13:45 |
| legacy NKD night slots | the in-memory flag for the previous business day | 01:10–02:55 |
| Track 1's freshness gate | `preflight_state.json` off disk | every Track 1 slot |

### The accident this section exists to prevent

The job sits in the middle of the legacy block in `run_scheduler.py`, for no reason other than
legacy having been written first. Retiring "the legacy jobs" by reading that file top to bottom
takes the data refresh with it.

The failure would be silent in the worst way. Nothing errors at retirement time. The next
morning Track 1's gate reports the pre-flight record as **missing** and refuses every entry —
and the reason it prints points at a *file*, not at the deleted job that stopped writing it.

### The rule

**When the legacy entry jobs are removed, these three must stay registered:**

* the 13:45 pre-flight
* the heartbeat
* the 23:55 session-report fallback

This is not a sentence to remember. It is held by
`global_index.track1_slots.route_classification()`, which buckets **every** registered job by
owner and puts anything matching no rule into `unclassified` — a state the Stage 5L tests
require to be empty. A job added tomorrow that nobody classified turns the suite red; a
hand-written list would simply have failed to mention it.

`legacy_retirement_candidates()` returns exactly what a retirement may remove. Nothing else.

### Morning Track 1 slots run on D-1 data, by contract

Calm at 10:00 and Stress 10:35–12:30 all fire **before** 13:45. What they decide on is the
previous business day's completed pre-flight plus today's live bars from the broker.

**That is the design, not a gap.** It is encoded in
`track1_freshness.required_data_through()`, which returns the previous business day for any
instant before 13:45 and today from 13:45 onward, and it is the contract every measured Track 1
number was produced under.

Adding a pre-market refresh would change that contract and silently invalidate those numbers.
If it is ever wanted, it is a decision with its own measurement — not a fix, and not a
side effect of some other stage. A Stage 5L test asserts no second refresh job exists.

### Two things that must not move

* **13:45.** The hour lives in two places — the scheduler trigger and the freshness gate — and
  a test compares them to each other so that moving one alone turns red.
* **The job's name.** `"Pre-flight update 13:45 ET"` looks like a display label and is not one:
  the dashboard's job journal maps a run back to a job by matching that name prefix. Rename it
  and every pre-flight run disappears from the journal without one error line — the mapper
  returns nothing and drops the run. Stage 5L deliberately left the name alone and states the
  ownership in comments and in the classification table instead, where saying it is free.

---

## 7. The root `STOP_TRADING` does not stop Track 1

*Added 2026-08-23 (Stage 5M-B). This is the opposite of what an operator would assume, and
assuming it wrongly is how a "stopped" system keeps dialling the broker.*

There are two kill switches and they are not interchangeable:

| Switch | Stops | Read by |
|---|---|---|
| `STOP_TRADING` (repo root) | **legacy entries only** | the legacy 14:05–15:55 slots and the NKD night slots |
| `STOP_TRADING.track1` | **Track 1 only** | the Track 1 entry point, every slot |

Placing the root switch stops legacy from trading. It does **not** stop the Track 1 slots. They
keep firing on their own schedule, and the ones wired to a provider keep opening a connection to
the Gateway on clientId 89.

For a shadow measurement that separation is exactly what you want — legacy stands down, Track 1
keeps observing, and the evidence is clean. But it means "I placed `STOP_TRADING`, the system is
stopped" is false while the Track 1 flag is on.

**To stand the whole system down, place both.**

### What the Track 1 slots do today, per slot

| Slots | Provider | Effect of firing |
|---|---|---|
| Calm 10:00, Stress 10:35–12:30 (25) | `ibkr` | connects on clientId 89, fetches bars, decides in shadow |
| **Normal-R4 14:05–15:55 (23)** | **`none`** | refuses by name, writes a ledger row, exits — **no connection** |

The swing slots were added in Stage 5M-B deliberately without a provider. They land on the same
minutes as the legacy entry slots, whose runs take a median of 194 s out of a 300 s window and a
measured maximum of 291 s. Nobody has measured what a Track 1 slot costs, because none has ever
run in production — so the no-provider stage is what makes that measurement possible without
putting a second broker child on every legacy entry minute.

Orders remain impossible throughout: the gate reports `B1_broker_account_or_legacy_retirement`
open, and no Track 1 slot carries `--allow-orders`.

---

## 8. Freezing legacy: what it does, and what it does not

*Added 2026-08-23 (Stage 5M-C), when the decision was taken to freeze legacy during the Track 1
shadow period rather than run the two side by side.*

### The intent

Place the root `STOP_TRADING`. Legacy stops taking new entries. Track 1 keeps observing, because
it reads its own `STOP_TRADING.track1` and that file is absent. The shadow evidence is then about
Track 1's decisions rather than about two routes interleaving.

### What the switch actually stops — read this before planning around it

`STOP_TRADING` **halts new entries. It does not stop legacy from running.**

A legacy slot with the switch in place still:

* spawns its child process,
* **connects to IBKR on clientId 1**,
* fetches bars for every instrument,
* rolls any contract expiring that day,
* runs the exit path — positions still exit on their exit day, deliberately,
* runs the broker/file reconcile and the stop checks.

Only the entry decision is skipped, and it is skipped late — inside `run_day`, after all of the
above. So the wall-clock cost of a frozen legacy slot is close to the cost of a live one, and
the Gateway load is the same.

**Consequence for planning:** "we froze legacy, so the 14:05–15:55 window is free" is false. If
the Normal-R4 slots are switched to a real provider they will still share those minutes with a
legacy child that is connected and fetching. That collision has never been measured — which is
why the switch below exists and why it is off by default.

### Turning the Normal-R4 provider on for a measured session

The 23 swing slots are declared with `--bar-provider none`. To run a session with them
connected:

```powershell
$env:RAITS_TRACK1_SWING_PROVIDER = "ibkr"
```

Unset, or empty, means `none`. Any other value is **refused at scheduler build time** — the
scheduler will not start. That is deliberate: an operator who typed `IBKR` and got a silent
fallback to `none` would have a session that collected nothing and no way to tell that from a
session where the slots ran and found no setups.

Calm and Stress are not affected by this variable. They have run with `ibkr` since Stage 5I and
a session-scoped switch must not be able to turn them off by accident.

### What is still not true

**Track 1 is not a full route.** It owns three sleeves of four:

| Sleeve | Track 1 slots | Status |
|---|---|---|
| Calm | 1 | connected |
| Stress | 24 | connected |
| Normal-R4 | 23 | staged, provider off by default |
| **NKD** | **0** | **no slot at all** |

Two things must happen before "Track 1 runs the combined route" is a true sentence:

* **Stage 5N** — NKD gets Track 1 ownership. Until then the overnight sleeve is decided by
  legacy, and freezing legacy means it is not decided at all.
* **Stage 5O** — route-aware safety. Stop repair and max-hold are still hard-wired to legacy's
  positions file, and the max-hold state file is shared, which fails silently when both routes
  hold positions.

Until both are done, a shadow period measures three sleeves and a frozen legacy leaves the
fourth untraded.

---

## 9. Track 1-only shadow — the clean validation path

> **Superseded in part — read §11 and §12 for the current picture.** This section was written
> at Stage 5M-D. Two of its statements have since stopped being true: Track 1 had no NKD slot
> (Stage 5N gave it 22, so all four sleeves are owned) and the safety sweeps all watched
> legacy's book (Stage 5O gave Track 1 its own 11-job safety net). The section is kept because
> the *reasoning* about the kill switch and the mode is still exactly right, and because
> deleting the record of what was true when would make the next reader trust the document
> less, not more.

*Added 2026-08-24 (Stage 5M-D), after the decision that legacy will be turned off and
eventually moved out of the production path.*

### The three scheduler modes

| Mode | Jobs | What runs |
|---|---|---|
| (default) | 60 | legacy only — byte-identical to what it has always been |
| `--track1-shadow` | 107 | legacy **and** Track 1. Transitional. Both routes run |
| **`--track1-only-shadow`** | **62** | **Track 1 plus shared infrastructure. Legacy strategy jobs are not scheduled** |

### Be precise about what the kill switch does

Section 8 said it and it bears repeating with the sharper conclusion: **`STOP_TRADING` halts
entries inside the legacy runner. It does not turn legacy off.** A legacy slot with the switch
in place still spawns its child, connects on clientId 1, fetches every instrument, rolls
contracts and runs the exit and reconcile path. The scheduler and job execution are untouched
by the switch.

"Turn off legacy" therefore means **do not schedule the jobs** — which is what
`--track1-only-shadow` does, and what no switch file can do.

### Why this mode is where Normal-R4 gets its provider

Stage 5M-C staged the swing provider behind `RAITS_TRACK1_SWING_PROVIDER` for one reason: the
swing slots land on the same minutes as the legacy 14:05–15:55 entry slots, and the cost of a
second connected child in those minutes was unmeasured. In Track 1-only mode those legacy jobs
do not exist, so the reason is gone **structurally** — and the swing slots default to `ibkr`
here, and only here. In the transitional mode they still default to `none`, because there the
reason still holds. The env var overrides in both directions either way.

### How to start it

```powershell
python monitor/ops.py restart --scheduler --track1-only-shadow
```

(`up` refuses the flag when a scheduler is already running, and refuses
`--track1-shadow --track1-only-shadow` together — they ask for different schedules.)

This mode does **not** require `STOP_TRADING`. There are no legacy entry jobs for it to halt,
and demanding it anyway would teach the operator that the switch is what stops legacy.

### What stays scheduled, and why

* **Shared infrastructure** — the 13:45 pre-flight (Track 1's freshness gate reads its record),
  the heartbeat, the 23:55 session-report fallback. Route-neutral, both routes need them.
* **The safety sweeps** — stop repair ×10 and the 09:31 max-hold exit. At Stage 5M-D these
  were **NOT** route-safe: both were hard-wired to `live_positions.json`, legacy's book, which
  made this mode *legacy-removable* but not yet *legacy-independent*.
  **Stage 5O closed that** — Track 1 now registers its own 11 safety jobs on
  `live_positions.track1.json`, and the legacy sweeps stay only as the DRAIN for positions
  still open in the legacy book. See §11 for the current split.

### Legacy-removability, measured

With `global_index.run_live_day` made unimportable (a meta-path block, catching every import
route), all of the following still work: the scheduler builds in all three modes, all 48
Track 1 slot closures fire with the right providers and `RAITS_ROUTE=track1_candidate`, and the
dashboard mirror builds with 48 Track 1 rows and zero legacy rows. No Track 1 module imports
the legacy entrypoint, and Track 1's only code-level mentions of legacy's state files are in
its own `LEGACY_PATHS` refusal list — files it names in order to guarantee it never writes them.

### What may be claimed, and what may not

**May:** Track 1-only shadow mode exists for the current Track 1 sleeves; legacy strategy jobs
can be omitted; the Normal-R4 provider collision with legacy is resolved structurally.

**May not:** full Track 1 route, live readiness, or paper readiness. *(As of Stage 5M-D. NKD
had no Track 1 slot then — Stage 5N added its 22 — and the safety sweeps still pointed at
legacy's book — Stage 5O split them.)* **The legacy route may be moved or deleted only after
5N + 5O + 5P pass**, which remains true: 5P is readiness to START the shadow period, not the
measured period itself.

---

## 10. Stage 5N — Track 1 owns all four strategy sleeves at slot/source level

*Added 2026-08-24. Plumbing, not research: the MNKD sleeve reuses the promoted engine at the
promoted settings — ema 10, chandelier config 2.5, five-day hold, lag-1 regime, one micro,
6% cap. Nothing about the rule changed.*

### The slot table after 5N

| Sleeve | Slots | Band (ET) | Provider: transitional / track1-only |
|---|---|---|---|
| Calm | 1 | 10:00 | ibkr / ibkr |
| Stress | 24 | 10:35–12:30 | ibkr / ibkr |
| Normal-R4 | 23 | 14:05–15:55 | none / **ibkr** |
| **MNKD** | **22** | **01:10–02:55** | **none / ibkr** |

70 slots. Jobs: 60 default · 129 transitional · **84 track1-only** (0 legacy strategy jobs).
MNKD joined the STAGED set for the same reason swing did: in the transitional mode the legacy
`nkd_night` jobs still occupy its band, so it runs without a provider there and takes `ibkr`
only in track1-only, where those jobs are not scheduled. The same env override applies
(`RAITS_TRACK1_SWING_PROVIDER` — the name is historical; it governs both staged sleeves).

### Two clocks, and what was actually found

The MNKD frame is carried on **Asia/Tokyo**; the scheduler is ET-native; Japan has no DST. The
ET slot band (01:10–02:55) equals the Tokyo session band (14:10–15:55) in **summer only** — in
winter they drift an hour apart, the late ET slots fire after the Tokyo window has closed, and
that is **legacy's own behaviour**, inherited on purpose. The admission gate speaks the session
truth: its NKD requirement is written in the Tokyo clock and will refuse winter slots
TOO_LATE.

Two real defects were found by measurement during this stage, both the 13-hour family:

* `detect_entry_for_slot` truncated its scan at `now` converted to **ET** — right for every
  frame it had ever seen, 13 hours wrong for the Tokyo frame. It now truncates on the frame's
  own clock.
* The window gate judged candidate stamps as bare wall-clock text against the ET band. The
  committed NKD replay rows are stamped +09:00 in the session window, and the gate silently
  rejected **26 of them, shrinking the replay's accepted tail from 91 to 67** — measured
  before any new test existed. Candidates are now judged on the sleeve's **session window in
  the sleeve's own clock** (`SESSION_WINDOWS` / `SESSION_WINDOW_CLOCKS`); the replay is
  restored to 91 accepted, 0 window rejections, and the fix is pinned by a full-replay test.

### Freshness

Every MNKD slot fires before 13:45 ET, so the sleeve reads the **previous business day's**
pre-flight — D-1, like Calm and Stress, measured per slot. Ledger window: 22 expected slots,
complete only at 22 decided; the ET session date and the Tokyo calendar date coincide for the
whole band in both DST regimes, so no midnight-crossing rule is needed.

### What may be claimed after 5N

**Track 1 owns all four strategy sleeves at slot/source level in track1-only shadow.**

Not claimed *as of Stage 5N*: legacy independence (stop repair and max-hold still watched
`live_positions.json` then — **Stage 5O has since split them**, see §11), paper/live
readiness, or permission to delete the legacy route (**5O + 5P** first).

---

## 11. Stage 5O — the safety net is route-aware

*Added 2026-08-24. Closes the audit's blocker L3 and the one dependency the Stage 5M-D
removability probe measured and refused to accept: every safety job watched legacy's book.*

### Two safety sets in track1-only mode, and why both

| | Legacy safety (drain) | Track 1 safety (new) |
|---|---|---|
| jobs | max-hold 09:31 + stop-repair sweeps | max-hold 09:31 + 9 weekday sweeps + Sunday 18:30 (11 jobs) |
| positions | `live_positions.json` | `live_positions.track1.json` |
| kill switch | `STOP_TRADING` | `STOP_TRADING.track1` |
| lock file | `runner.pid` | `runner.track1.pid` |
| client id | 1 | **90** (data slots use 89; a sweep must not collide with a slot still holding it) |
| max-hold marker | `maxhold_state.json` | `maxhold_state.track1.json` |

**The legacy set stays deliberately** — it is in the safety bucket, not the retirement set.
Any position still open in legacy's book keeps its stop repair and its five-day exit while it
drains. Removing it is part of deleting legacy, which is gated on 5P.

**The markers are separate files, and that is the point.** A shared "already ran today" file
is how one route's run silently suppresses the other's: the second route reads a mark it did
not write, concludes the sweep is done, and a five-day position stays open. The scheduler now
carries two markers and two catch-ups, and a test proves the legacy marker cannot suppress the
Track 1 catch-up in either direction.

### Costs and behaviour worth knowing

* The Track 1 sweep hours are **derived from Track 1's own entry windows** (no sweep inside
  01:10–02:55, 10:35–12:30, or 14:05–15:55) — today that yields the same nine weekday hours
  legacy keeps, so in track1-only mode **both safety sets fire on the same minutes**: two
  short-lived children per sweep, different locks, different client ids. Unmeasured against a
  live Gateway, like everything else — a 5P measurement item.
* `run_maxhold_exit` returns **before connecting** when its positions file does not exist, so
  during a pure shadow period (no Track 1 book yet) the Track 1 safety jobs cost one process
  each and open nothing.
* `ops.py status` now prints `track1_safety_routes` — which route's safety net is scheduled —
  and distinguishes `track1-only-shadow` from the transitional mode by reading the running
  process's own command line.

### What may be claimed after 5O

**Track 1-only mode is legacy-independent at strategy + safety scheduler wiring level.**

Not claimed: paper/live readiness; safe-to-delete-legacy before the 5P full-shadow period
passes; broker-flat or orphan-STP cleanliness — those are statements about the ACCOUNT and
have not been measured against IBKR.

---

## 12. Stage 5P — starting the full four-sleeve shadow, and how a day is judged

*Added 2026-08-24. This section is the operator's page: the command, the environment, and the
gate the evidence will be graded by.*

### The command

```powershell
python monitor/ops.py restart --scheduler --track1-only-shadow
```

That is the whole start. Ops sets the environment for the child — `RAITS_TRACK1_ONLY=1`,
`RAITS_TRACK1_SHADOW=1`, `RAITS_WINDOW_LEDGER_DIR` and `RAITS_TELEMETRY_DIR` pointed at
`global_index/track1_runtime/…` — and strips `TRACK1_ORDERS_APPROVED` from the child
regardless of what the launching shell carries. Exporting those by hand is not required and
not recommended; a hand-export into the wrong shell is how a scheduler collects nothing.

**No order path exists in this mode.** The gate registry holds B1 open, no slot carries
`--allow-orders`, the confirmation file does not exist, and the launcher removes the order
env var. Enabling orders is NOT part of 5P — it is a separate, later, gated decision.

**Legacy drain**: the legacy safety jobs stay registered against `live_positions.json` until
that book is empty. That is deliberate protection for the drain, not a leak.

### What runs

95 jobs: 70 Track 1 strategy slots (Calm 1 · Stress 24 · Normal-R4 23 · NKD 22, all with a
real bar provider), 11 Track 1 safety jobs against Track 1 paths, 11 legacy drain safety
jobs, 3 shared infrastructure. Zero legacy strategy jobs.

### How a shadow day is judged

`global_index/track1_shadow_acceptance.py` — committed before any shadow day exists, so the
thresholds cannot drift toward the first day's results:

| Check | Required |
|---|---|
| coverage, per sleeve | window COMPLETE: 1 / 24 / 23 / 22 decided slots, with a close record |
| slot gaps | every registered slot id wrote a ledger row (a count can hide one silent + one doubled) |
| runtime | **p95 < 300 s** (the cadence); p95 < 240 s is the target — a miss warns, does not fail |
| stalls | no single slot at or over 300 s |
| orders | none attempted, B1 still open, no confirmation file |
| freshness | every explanation row carries a freshness proof |
| explanations | present for the day |
| checkpoint | exists, names this route, cut on the judged day. Identity-hash acceptance is separately `not_checked_here` — run `route_checkpoint.usable` per sleeve for it |

A day without telemetry **fails** — a day nobody measured cannot be accepted as within
budget. The dashboard reads the same runtime paths (`/api/v1/track1-runtime`), and the legacy
positions endpoint is now labelled as the legacy route so a drain book cannot be read as
Track 1 state.

### After the period

`evaluate_period(days)` accepts only when every day is accepted. Then — and only then — the
questions that remain are the account-level ones this gate deliberately does not answer:
broker-flat, orphan-STP, and the retirement decision itself.

---

## Appendix — the post-window audit (Stage 5Q, 2026-08-24)

The shadow period is measured by `global_index/track1_shadow_acceptance.py`. Since this stage
that gate is also **asked automatically**, by a scheduled job rather than by a human running a
dated script.

### Commands

```powershell
# every sleeve of the most recent session day, plus the day roll-up
python -m global_index.track1_shadow_audit --latest --all

# one window, after it closes
python -m global_index.track1_shadow_audit --date 2026-08-25 --sleeve global_nkd

# a whole shadow period
python -m global_index.track1_shadow_audit --from 2026-08-25 --to 2026-08-29 --all

# look, write nothing
python -m global_index.track1_shadow_audit --latest --all --dry-run
```

Records land in `global_index/track1_runtime/audits/track1_audit_YYYYMMDD.jsonl`, append-only
and route-stamped. The audit reads the evidence and never writes into it.

### The jobs, and when they fire

`--track1-only-shadow` only. Nothing here connects to IB Gateway, sends an order, or spawns
`run_live_day_track1`.

```text
03:05 ET  track1_audit_global_nkd      the NKD window that closed at 02:55
10:10 ET  track1_audit_roska4_calm     the Calm shot at 10:00
12:40 ET  track1_audit_roska4_stress   the Stress window that closed at 12:30
16:05 ET  track1_audit_roska4_swing    the Normal-R4 window that closed at 15:55
16:15 ET  track1_audit_daily           all four, plus the committed daily gate
```

Scheduler inventory in this mode is now **100** jobs: 70 strategy + 11 Track 1 safety +
**5 audit** + 11 legacy drain safety + 3 shared infrastructure + 0 legacy strategy.

### Reading a verdict

| Verdict | What to do |
|---|---|
| `PASS` | nothing. The window closed under scheduler uptime and left complete evidence |
| `WARN` | read the reason. Today the only WARN is p95 at or over the 240 s target and under the 300 s ceiling |
| `NOT_ENOUGH_DATA_YET` | nothing was proved and nothing failed. Either the window has not closed, or the scheduler was not up for all of it, or the start instant could not be read and the window left no evidence at all |
| `FAIL` | a judgeable window has a gap. The reason codes name which one |

`NOT_ENOUGH_DATA_YET` is **not** a mild failure and is deliberately off the PASS/WARN/FAIL
ladder. A window that closed before the scheduler existed produced no evidence because nothing
was ever asked to run — the 2026-08-24 NKD window (01:10-02:55 ET, scheduler up at 04:32 ET)
is the measured case, and calling it a failure is how an operator learns to stop reading the
audit.

**An audit that has not run is not a pass.** The dashboard's Track 1 Runtime panel carries an
**Audit verdict** row that says `audit not run yet` in words rather than leaving a blank.

### Restart timing

Restarting the scheduler makes every window that already closed **today** read as pre-start,
because no process existed to run those slots on the new instance. So a mid-day restart is not
harmful, but it does mean the day cannot be judged: prefer a restart before the first window
of the session (10:00 ET), or accept that the remaining windows are what the day will be
judged on.

The audit itself can always be run by hand against any past day without restarting anything.

### What the audit is not

It grades the shadow evidence. It does not decide `B1_broker_account_or_legacy_retirement`,
it does not arm the order gate, and a `PASS` from it is not a go-live. The preconditions in
this runbook still have to be satisfied in order, and the confirmation file is still the only
thing that moves the gate.

---

## Appendix addendum — reading an audit verdict after Stage 5Q-1 (2026-08-24)

### The command in the 5Q appendix for the backend was wrong

There is no `--backend` flag. Backend-only, with the Track 1 slot table:

```powershell
python monitor\ops.py restart --no-scheduler --track1-only-shadow
```

The scheduler does **not** need restarting for the audit: the five audit jobs are already
registered, and Stage 5Q-1 changed only modules the audit child imports fresh on every spawn.
A scheduler restart costs the current day's judgement — every window that already closed reads
as pre-start on a new process — so do it only when the scheduler itself needs replacing.

### "Complete" now means every slot LOOKED, not every slot DECIDED

A slot can end without deciding and still have observed its window. Two cases, both by design:

- it evaluated and found no candidate — this always counted, and records `decided=True`;
- the intraday gate told it the **sleeve's own decision band** was shut (`too_early`,
  `too_late`). For NKD that band is the Tokyo session while the slot grid is fixed in ET, so
  after **2026-11-01** twelve of the twenty-two ET slots fall outside it. That is legacy's
  inherited behaviour, not a fault.

Everything else that stops a slot deciding — no bars, no source, a stale or gapped frame, or
an admission taken while the daily inputs were refused — is the route being **unable to
evaluate**, and it still fails the window.

### The verdicts you will actually see

| verdict + reason | what to do |
|---|---|
| `PASS` / `all_slots_observed_no_action` | nothing. Every slot ran, evaluated, found nothing |
| `WARN` / `all_slots_observed_window_shut` | look once. Legitimate for NKD in winter; also what a misconfigured grid looks like |
| `WARN` / `duplicate_slot_ids` | a slot wrote twice with nothing missing. Odd, not a gap |
| `FAIL` / `slot_could_not_evaluate` | the route could not read its inputs. The reason names which |
| `FAIL` / `missing_slot_ids` | a slot left no row. A doubled row never fills this |
| `FAIL` / `slot_without_timing` | it ran and nobody measured it |
| `FAIL` / `timing_without_ledger_row` | it started and never said what it saw — a crash, or a mutex skip |
| `FAIL` / `explanations_missing` | candidates were seen and no row exists anywhere for the day |
| `NOT_ENOUGH_DATA_YET` | the window has not closed, or the scheduler was not up for all of it |

`coverage_incomplete` appearing **beside** a PASS or WARN is not a contradiction: it is the
committed ledger rule reporting that it counts only slots that decided. Both numbers are in
the record — `observation` is the audit's, `ledger_outcome` is the gate's.

### One thing a green audit does NOT prove yet

`explanations_overwritten_by_a_later_sleeve` means the day's explanation file was truncated by
a slot that ran after this sleeve. Every live slot opens that file with `mode="w"` and all four
sleeves share one file per session date, so only the last slot's rows survive. The audit names
this and does not charge it to the sleeve — and it also means **per-candidate explanation
attribution is not verified** on any day that reason appears. It is recorded as a blocker
against the runner, not against the audit.

Until it is fixed, do not read a green day as evidence that the explanation record is complete.

---

## Appendix addendum — explanation evidence after Stage 5Q-2 (2026-08-24)

### Where a slot's explanations are

```text
global_index/track1_runtime/shadow/explanations/
    live_<YYYY-MM-DD>/<sleeve>/<slot_id>/explanations_<YYYYMMDD>.jsonl
```

One file per slot. Re-running a slot replaces **that slot's** rows and nothing else, so a
day's row count is a count rather than an artefact of which slot happened to finish last.

Before this stage all four sleeves shared one file per session date and every slot truncated
it, so the day ended holding only the last slot's rows. Any row written before the fix is
still readable — the reader searches every shape.

Replay output is unchanged and stays where it was:
`scratch/track1_shadow/explanations/<window>/`.

### Reading the freshness verdict off a row

Structured, not a word search:

- a **DECISION** row carries `inputs_summary.freshness_allow` — the run's verdict, boolean;
- an **accepted** admission in a live/armed mode also carries a `freshness_allow` entry in
  `feature_snapshot` and cites `GATE.FRESHNESS`;
- a **rejected** row carries the feature only if the rule it cites uses it. A cap refusal
  never consulted the freshness gate and is not asked to prove one;
- the per-slot **NO_ACTION** context row carries the boolean feature — that is the record the
  day's freshness verdict is audited from.

`explanation_without_freshness_proof` in an audit now means a row failed that structural
check. It no longer fires because the word was missing from prose, and it no longer passes
because the word was present in prose.

### New reasons you may see, and what they mean

| reason | meaning |
|---|---|
| `explanations_missing` | slots saw candidates and no row exists anywhere for the day |
| `explanation_without_freshness_proof` | a row owes a typed freshness proof and does not carry one |
| `explanations_overwritten_by_a_later_sleeve` | the pre-5Q-2 truncation. A healthy day no longer produces it; if it appears, the rows are from before the fix |

### Known blockers as of this appendix

- **the live frame cannot be spliced.** The IBKR fetch returns `average` and `barcount`, which
  the frozen frames do not have, and `track1_live_frame.splice` refuses rather than
  concatenating into NaN holes. Measured 2026-08-24: the 10:00 Calm slot crashed on it. Until
  the live fetch is projected onto the frozen columns, every slot of every sleeve refuses and
  no window can be judged.
- **`SpliceRefused` is not caught by the slot**, so it leaves no `slot_observed` row and the
  audit can only report `coverage_unobserved` where a named refusal would have said what
  happened.

Neither blocks the audit machinery; both block a judgeable shadow day.

### Operator

No action required by Stage 5Q-2. Slots import their modules fresh on each spawn, so a
scheduler restart buys nothing and costs the current day's judgement. The backend restart —
`python monitor\ops.py restart --no-scheduler --track1-only-shadow` — only refreshes what the
Explanations panel shows.

---

## Appendix addendum — reading a live-frame refusal (Stage 5Q-3, 2026-08-24)

### The join no longer dies on the feed's extra columns

The IBKR feed returns `average` and `barcount` on top of the frozen schema. Those are now
**dropped** before the join, by `track1_live_source.live_frame` — the one place that calls the
splice guard. The guard itself is unchanged and still refuses two frames whose columns differ,
which is what catches a caller who skips the projection.

A live half **missing** a frozen column is still refused, by name and naming the column
(`missing_required_columns`). Nothing is ever synthesised: a made-up `volume` of 0 is a bar
every indicator downstream would treat as measured.

Dropped names travel with the frame. If a NEW name shows up in `dropped_columns`, the feed
changed shape — worth a look, not an alarm.

### New slot reasons you may see

| reason | meaning | audit class |
|---|---|---|
| `live_frame_refused` | the splice guard refused; its own code is in `detail` (`column_mismatch`, `tz_mismatch`, `duplicate_timestamps`, `history_mutated`) | hard refusal → FAIL |
| `missing_required_columns` | the feed did not send a column the frozen frame has | hard refusal → FAIL |
| `nan_in_required_columns` | the feed sent a bar with no price | hard refusal → FAIL |
| `overlap_disagreement` | the feed and stored history disagree on a shared timestamp's price | hard refusal → FAIL |

All four are **observed** refusals: the slot ran, looked, and said why. The audit reports
`slot_could_not_evaluate` and names them. What it must never say for these is
`coverage_unobserved` — that means nobody looked, and before this stage a splice refusal
produced exactly that misreading because the slot crashed before writing its row.

### Slot timing exists now

Track 1 strategy slots emit to `slot_timing/` for the first time. `outcome: ok` means **the
slot ran**, not that it decided — a refusal recorded by name is a successful observation, and
its runtime belongs in the cadence numbers. First measured runtimes: **~2.7 s**, against a
240 s target and a 300 s ceiling.

If a sleeve's audit says `no_timing_records`, that now means something: the slots did not run,
or `RAITS_TELEMETRY_DIR` is not set in the child environment.

### The open live blocker

**One MNQ history bar disagrees with the live feed** — 2026-08-21 13:45 ET, `low`: history
29400.25, feed 29395.75. Every Stress slot refuses on it, and MNQ is in the swing basket too.
The check runs before the splice, so this is not fixed by anything schema-related.

Two readings of the same instrument at the same instant cannot differ. Deciding which one is
right — and whether to repair the parquet or re-source the bar — is a stored-history decision
and belongs with whoever owns that data, not with a runtime fix.

Until it is resolved: Stress refuses by name every slot, and the refusal is recorded, timed
and audited.

### Operator

Nothing to restart for this stage. Slots import their modules fresh on each spawn, so a code
change reaches the next slot without a scheduler restart, and the dashboard reader is
unchanged. If a refreshed UI is wanted for an earlier stage's panel, the command is
`python monitor\ops.py restart --no-scheduler --track1-only-shadow` — there is no `--backend`
flag.

---

## Appendix addendum — the two data blockers (Stage 5Q-4, 2026-08-24)

### B-5R-E — the freshness gate cannot pass, and this is the one to fix first

The 13:45 pre-flight runs `update_ibkr_daily` then `update_spy_csv`. It is the **only** data
refresh in the schedule. `update_spy_csv` fetches through "today" at 13:45 ET — before the
16:00 close — so the regime CSV gains day **D−1** at day **D**'s pre-flight, while the
freshness gate's `required_data_through` returns **D** from 13:45 onward.

Measured 2026-08-24: preflight `2026-08-21: true`, CSV last date `2026-08-20`, required
`2026-08-21`, `regime_csv: stale`, `allow: False`.

**`shadow_live` binds the freshness gate**, so no candidate can be admitted at any instant
until this is settled. Slots still run, still observe and still refuse by name — which is why
this is visible at all.

Two ways out, and both are decisions rather than fixes:

- a second SPY refresh after the close, so the CSV reaches D on day D; or
- a requirement that asks for D−1 rather than D, if D−1 is genuinely what the rules trade on.

Do not pick one by editing the threshold. What the route considers fresh is a rule.

### B-5R-D — one MNQ bar, and B-5R-F, why there will be more

MNQ `2026-08-21 13:45 ET` holds `low = 29400.25`; the feed says `29395.75`. One bar out of 1186
shared timestamps, twelve independent fetches agreeing, and it is the **last bar in the file**.
The feed's low is LOWER — the only direction a partial minute's low can be wrong in.

The cause is the appender: `update_ibkr_daily` takes `new_bars[... > last_existing]`, strictly
newer, so the bar the fetch stopped on is never revisited. Every 13:45 leaves one. That is
**B-5R-F** and it is why repairing a single bar is a day's relief, not a fix.

**Never widen `_refuse_overlap_disagreement`.** Two readings of the same instrument at the same
instant cannot differ; the guard is the only thing that noticed this, and a price tolerance
would make the route join a frame it knows is wrong, silently, for ever.

### The repair tool

`scratch/track1_stage5q4_repair_boundary_bar_20260824.py` — **dry run by default**, and the
dry run writes nothing to the parquet.

```powershell
# safe at any moment the Stress window is closed (after 12:30 ET). Writes nothing.
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ
```

An apply needs `--apply` **and** `--expect <sha256 printed by the dry run>`. It snapshots the
parquet first and re-reads the snapshot to check it, bounds the repair to a window and a bar
count, refuses outright on anything outside them, refuses if the index would change, and
verifies by re-reading the file afterwards.

**Do not apply it yet.** Only `low` has been compared — the guard stops at the first differing
column, so `close` and `volume` on that bar are unmeasured. Applying needs a broker fetch,
which opens a second client beside the Stress slots on client id 89, and two clients on one id
has already cost this system six entry slots.

### What arrives on its own

```text
14:05 ET   the Normal-R4 slots are the first to touch MYM and M2K
01:10 ET   the NKD slots are the first to touch MNKD
```

If either reports `overlap_disagreement`, the boundary-bar mechanism is confirmed on more
instruments. If they join cleanly, MNQ is the only file carrying a bad bar today. Either answer
lands in the window ledger without anybody connecting to anything.

---

## Appendix addendum — operator changes from Stage 5Q-5 (2026-08-24)

Two of the three data blockers are fixed in code. **Only one part is live without a restart**,
so the operator instructions below are the whole of what changes.

### Nothing is required today

Today's 13:45 pre-flight behaves exactly as yesterday's: the new appender code runs, the
`--repair-boundary` flag is not passed, and every path is the one that ran before.

The corrected freshness requirement IS live — slots import it fresh on each spawn — so from
13:45 the gate stops refusing for a reason that was not true.

### The sequence, when you want the rest

```powershell
# 1. Measure the MNQ boundary bar. Writes NOTHING. Safe once the Stress window closes (12:30 ET).
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ

# 2. Repair it — only after reading step 1. Snapshots the parquet and verifies by re-reading.
python -m global_index.update_ibkr_daily --repair-boundary --symbols MNQ

# 3. Bring the 16:20 post-close SPY refresh online.
python monitor\ops.py restart --scheduler --track1-only-shadow

# 4. Let the dashboard learn about it.
python monitor\ops.py restart --no-scheduler --track1-only-shadow
```

`restart --help` verified: there is no `--backend` flag; backend-only is `--no-scheduler`.

**Step 2 rewrites a bar in shared history.** It refuses unless the feed's version is a
*completion* of the stored one — open unchanged, low no higher, high no lower, volume no
smaller — and it snapshots to `.pre5q5-<stamp>.bak` first. Do not run it while the Stress
window is open.

**Step 3 costs the current day's judgement.** Every window that already closed reads as
pre-start on a new process. Prefer before 10:00 ET or after 16:00 ET.

### What changes on the schedule

The job count goes **100 → 101** in track1-only shadow (60→61 default, 129→130 transitional).
The new job is:

```text
16:20 ET  spy_refresh_pm   SPY daily refresh (post-close)
```

It runs `update_spy_csv` only — no IBKR fetch, no `preflight_state.json` write. If it fails,
that is **not** a pre-flight failure: nothing that day depended on it, and tomorrow's Track 1
slots will simply refuse on `regime_csv: stale` until it is re-run.

It is classified shared infrastructure, so a legacy retirement must not remove it — both
routes read that CSV.

### Reading the freshness record

The gate now reports two requirements, because the two data kinds become available at
different times:

```text
requirement  ok  intraday through 2026-08-21 on raits.live.trading_calendar;
                 daily close through 2026-08-21
```

- **intraday** — what the minute-bar parquets must cover. Previous trading day before 13:45,
  today from 13:45.
- **daily close** — what the SPY series must cover. The last trading day *before* today, all
  day long, because a session on day D trades the regime label of D−1.

A new line may appear:

```text
preflight_consistency  stale  the pre-flight record for <day> says the 13:45 job SUCCEEDED,
                              and ['regime_csv'] still do not satisfy what the gate asks
```

That means the job ran and reported success and an input is still short. It is a **contract**
question, not a retry — re-running the 13:45 job will not change it. It stays silent when the
pre-flight itself failed, which IS a retry.

### Still open

> **Superseded on the evening of 2026-08-24 — see the Stage 5Q-6 addendum below.**
> `--repair-boundary` IS now in the scheduler's argv, and the MNQ bar named here has
> fallen out of the fetch overlap and been replaced by three new ones.

- **the MNQ bar** — until step 2 above, every Stress slot refuses `overlap_disagreement`.
- **`--repair-boundary` is not in the scheduler's argv**, so a new partial boundary bar can
  still be created at each 13:45. Making it permanent is a scheduler edit plus a restart, and
  it is deliberately left as a decision: it is the only path in the updater that rewrites a
  bar the parquet already has.
- **NKD after 2026-11-01** — twelve of twenty-two ET slots outside the Tokyo band, reported as
  WARN.
- **B1** — the order gate. Orders remain impossible.

---

## Appendix addendum — operator changes from Stage 5Q-6 (2026-08-24, evening)

This supersedes the "Still open" list of the 5Q-5 addendum above. Two things there have
changed: `--repair-boundary` **is** now in the scheduler's argv, and the MNQ bar that was to
be repaired has fallen out of the fetch overlap and been replaced by three new ones.

### There is work to do tonight, in this order

> **Steps 1 and 2 were carried out at 20:20 ET on 2026-08-24 and are done.**
> Steps 3 and 4 — the two restarts — are still outstanding. See the Stage 5Q-7
> addendum below, which also adds a rule this list does not have: do NOT run
> `update_ibkr_daily` outside its 13:45 slot while the market is trading.

```powershell
# 1. Repair today's three partial boundary bars.
#    Safe only while every Track 1 window is closed. Right now nothing opens until 01:10 ET.
python -m global_index.update_ibkr_daily --repair-boundary --symbols MNQ MYM M2K

# 2. Confirm. Writes nothing.
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MYM
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst M2K
#    each should print   verdict: nothing_to_repair

# 3. Restart, BEFORE the 01:10 ET NKD window so that window is fully covered.
python monitor\ops.py restart --scheduler --track1-only-shadow
python monitor\ops.py restart --no-scheduler --track1-only-shadow

# 4. Confirm.
python monitor\ops.py status
```

**After step 3, check:** job count **101** in track1-only mode · `spy_refresh_pm` present at
16:20 ET · `SPY_REFRESH_PM` in the dashboard mirror · `track1_mode=track1-only-shadow` ·
legacy strategy jobs **0** · Track 1 strategy/safety/audit **70 / 11 / 5** ·
`orders_possible=False` with `B1_broker_account_or_legacy_retirement` still blocking.

### Why tonight and not tomorrow morning

Every Track 1 window for 2026-08-24 has already closed **and been audited** — the eight audit
records are written and durable. The next window is NKD at 01:10, so a scheduler started this
evening covers it completely; restarting tomorrow morning would leave NKD
`NOT_ENOUGH_DATA_YET` for a second day running.

**The cost, exactly.** After a restart, any *future* audit of 2026-08-24 will report its
closed windows as `window_closed_before_scheduler_start` — pre-start, not judgeable. Read
today's verdicts from the records already written rather than re-deriving them. Nothing is
deleted.

### What `--repair-boundary` now does every day at 13:45

The pre-flight passes it. At each run the updater may **rewrite the last bar the parquet
already holds** — and only that bar — when the feed's version is a *completion* of it: `open`
unchanged, `low` no higher, `high` no lower, `volume` no smaller, and within 0.5%. Anything
else refuses by name and the whole pre-flight is marked **failed** (`sys.exit(1)`), so a
refusal is visible rather than silent. A day with no replacement is byte-identical to before
and takes no snapshot.

This was enabled on measurement, not on principle: one pre-flight on 2026-08-24 left partial
bars in **three of five** instruments, and Friday's equivalents refused 46 Track 1 slots.

### One instrument is not covered by any of this

```text
MNKD   1052 bars disagree with the feed, the first at 2026-08-24 07:01 JST
```

That is not a boundary bar, and the repair tool correctly refuses it
(`disagreement_outside_the_window`). **Its cause is unmeasured.** It needs its own audit before
NKD can be judged, and no guard should be widened to make it quiet.

### Reading the boundary measurement before repairing

```powershell
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ
```

Writes nothing, connects on **client id 95** — deliberately clear of Track 1 data (89), Track 1
safety (90), legacy (1) and the daily updater (2). Two clients sharing an id has already cost
this system six entry slots.

---

## Appendix addendum — operator changes from Stage 5Q-7 (2026-08-24, late evening)

Two of the four steps in the 5Q-6 list are done. What remains, plus one new standing rule and
one identity contract that must never be collapsed again.

### What is left tonight

```powershell
# Bring the corrected scheduler up. BEFORE the 01:10 ET NKD window.
python monitor\ops.py restart --scheduler --track1-only-shadow

# Let the dashboard learn about the new job.
python monitor\ops.py restart --no-scheduler --track1-only-shadow

python monitor\ops.py status
```

**After the first restart, check:** job count **101** in track1-only mode · `spy_refresh_pm` at
16:20 ET · `SPY_REFRESH_PM` in the dashboard mirror · `--repair-boundary` in the 13:45
pre-flight argv · legacy strategy jobs **0** · Track 1 strategy/safety/audit **70 / 11 / 5** ·
`orders_possible=False` with `B1_broker_account_or_legacy_retirement` still blocking.

### A new standing rule: do not run the appender off-schedule

```text
DO NOT run `python -m global_index.update_ibkr_daily` while the market is trading,
except at its own 13:45 slot.
```

It appends bars strictly newer than the last stored one, and while the market trades the fetch
always ends inside an **open** minute. So every run stores one partial bar, and running it again
to clear that bar just creates another a minute later. Measured on 2026-08-24: the 13:45 bars
were repaired at 20:20, and the same run left new partial bars at 20:20 and 20:21.

`--repair-boundary` at the next 13:45 will clear it. Let it.

### What to expect in tomorrow's audit, so it is not read as a new fault

```powershell
python -m global_index.track1_shadow_audit --latest --all --dry-run
```

The basket sleeves should refuse on **exactly one** bar each — `2026-08-24 20:20` for MNQ,
`20:21` for MYM and M2K. That is predicted. **MES and NKD should be clean.** Anything more than
one bar, or a different timestamp, is new and worth stopping for.

### The identity contract — three names, and which layer owns each

```text
                 runner name    history symbol    order symbol
MES / MNQ /      the name       the same          the same
MYM / M2K
MNKD             MNKD           NKD               MNK
```

- **History symbol** — what to ask IBKR for when the answer must line up with the parquet.
  Owned by `update_ibkr_daily`, because that is the module that fetched the files. Read it with
  `history_ibkr_symbol(inst)`; the live route reaches it through
  `track1_live_source.history_symbol(inst)`.
- **Order symbol** — what goes on an order. Owned by `_RAITS_TO_IBKR`, built from
  `Contract.ibkr`. Unchanged by Stage 5Q-7.

**Never use `Contract.data_symbol` to decide what to fetch.** It is the file stem, and it
disagrees with the fetch symbol on four of five instruments — MES's is `ES`, the full-size
E-mini. Using it would repeat the ten-times-size incident on four contracts at once.

Why MNKD is split at all: the micro MNK has history only from 2024 Q4, while the backtest runs
on full-size NKD from 2018. Both track one index, so signals are comparable; only the
multiplier differs, and the multiplier belongs to sizing and P&L, never to a bar price.

Measured 2026-08-24, one read-only fetch per arm over the same 1,186 minutes: asking for MNK
disagreed with history on 1,155 of them; asking for NKD disagreed on none.

### Reading a boundary measurement

```powershell
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ
```

Writes nothing. Connects on **client id 95** — deliberately clear of Track 1 data (89), Track 1
safety (90), legacy (1) and the daily updater (2). The MNKD symbol probe uses the same id:

```powershell
python scratch\track1_stage5q7_mnkd_identity_probe_20260824.py
```

---

## Appendix addendum — the identity contract after Stage 5Q-9 (2026-08-24, night)

No operator command changed. What changed is the **identity contract** — what the route
declares itself to be, and therefore what a checkpoint is accepted or refused on.

### Every Track 1 params hash moved. That is intended.

```text
roska4_swing  MES   sha256:5a74de46…     roska4_calm    MES   sha256:50768f10…
roska4_swing  MNQ   sha256:d5e700c3…     roska4_calm    MNQ   sha256:c08f7cfb…
roska4_swing  MYM   sha256:56c4ad07…     roska4_stress  MNQ   sha256:2f8a4420…
roska4_swing  M2K   sha256:1b6effc8…     global_nkd     MNKD  sha256:19eef4ec…
```

Nothing was invalidated: `replay_checkpoint.track1.json` does not exist and the legacy
`replay_checkpoint.json` carries no `params_hash` entries. If a Track 1 checkpoint is ever
written under an older hash, **a `PARAMS_MISMATCH` refusal is the mechanism working** — do not
loosen the identity to make it resume; re-bootstrap under the current one.

### An instrument has three names, and the hash now carries all three

```text
                 what it READS          what it TRADES        what it is WORTH
MES/MNQ/MYM/M2K  its own symbol         its own symbol        $5 / $2 / $0.50 / $5
MNKD             NKD  (full size)       MNK  (micro)          $0.50
```

- **signal data identity** — `data_source_identity`, path + sha256 of the parquet.
- **tradable identity** — `tradable_symbol`, from `Contract.ibkr`, the same attribute the
  broker's order map is built from.
- **point value / tick** — from the same contract record.
- **sizing basis** — which risk formula the cap gate is fed.

**MNKD splits NKD bars from MNK orders on purpose.** The micro has history only from 2024 Q4
while the backtest runs on full-size NKD from 2018; both track one index, so the signals are
comparable and only the multiplier differs. Measured: asking IBKR for MNK and comparing against
this history disagreed on 1,155 of 1,186 shared minutes; asking for NKD disagreed on none.

**Never collapse the two, in either direction.** Sending an order to the data symbol is the
2026-08-14 defect — ten times the intended size, −$1,400 at the broker against −$140 in the
ledger. Reading bars from the order symbol is the Stage 5Q-7 defect. Both now move the hash.

### Sizing basis — read a risk figure knowing which one it is

```text
roska4_swing, global_nkd    artifact_mult_x_daily_atr    risk = 2.5 x daily ATR x pv x qty
roska4_calm, roska4_stress  true_stop_distance           risk = |entry - stop| x pv x qty
```

The two ATR-stop sleeves are sized on a proxy because that is what their artifacts were
**admitted** under, and the caps were measured against it. From 2026-08-24 the live route uses
the same, so a live candidate's `risk_dollars` is 25% larger than it was before that date and
the route admits **fewer** positions.

Switching them to the true stop distance changes **166 admissions** across the three measured
windows and turns vault2026 from +$8,260 to +$5,872. It is a re-rate, not a tidy-up. Do not
change `SIZING_BASIS` without one.

### Reading a cap-usage figure

Cluster and family **gross** is `max(long, short) / account`, not the sum of both sides. A
gross figure above the cap is impossible and means whatever produced it is measuring something
else.

A **net** figure above the cap is possible and is not a breach: the cap gates new risk at
admission, and after a scheduled close removes one side of the book the remaining imbalance can
sit above it until the next candidate is refused. Verified across the floor window — no
admission and no forced close has ever left a cluster above its net cap.

### `global_nkd` in an explanation record

It now reports `stop_basis: fixed_entry_atr` with `stop_multiple 2.0`, anchored at the entry,
ratchet off, armed 14:05 on the Tokyo clock. It read `chandelier_atr` until 2026-08-24 while
the stop on the book was the entry-anchored band — if you have older records, that is why.

---

## Appendix addendum — the intraday updater after Stage 5R-0 (2026-08-25)

**The updater must never persist an in-progress final minute.** From 2026-08-25 it does not:
a bar stamped T is stored only once the fetch instant has reached T + 1 minute. The instant is
stamped *before* the request goes out, so every bar kept had already closed before IBKR was
asked and the values held for it are final.

**`--repair-boundary` repairs the PREVIOUS boundary bar, never the currently open one.** The
two are different jobs and both are needed for now:

```text
5R-0                 stops a NEW partial bar being written        live from tomorrow's 13:45,
                                                                  no restart needed
--repair-boundary    repairs one already in the file              needs the scheduler restart
```

Once the three partial bars left in MNQ, MYM and M2K on 2026-08-24 have been cleared,
`--repair-boundary` should never find anything again. If it reports a replacement after that,
something wrote a partial bar and it is worth stopping for.

### What the 13:45 log should look like

```text
  MES: final-bar check — kept: final bar had closed before the fetch
  MNQ: final-bar check — dropped: 2026-08-25 17:45:00 is still open at 17:45:12
                                  (complete at 17:46:00)
...
IN-PROGRESS FINAL MINUTES NOT STORED (Stage 5R-0, intentional):
  MNQ   2026-08-25 17:45:00  — still open at fetch; it arrives on the next run
```

A dropped tail is **not** a failure and does not mark the pre-flight failed. The minute arrives
on the next run as an ordinary new bar. The parquet simply ends one minute earlier than the
fetch reached, which is the correct end state.

**Do not run `update_ibkr_daily` outside its 13:45 slot while the market trades.** That rule
from the Stage 5Q-7 addendum still stands, but its reason has changed: it no longer creates a
partial bar. It now just advances the file to a point the next run would have reached anyway,
for no benefit, on a shared data file.

---

## Appendix addendum — verifying the dashboard mirror (Stage 5R-1, 2026-08-25)

No operator command changed in Stage 5R-1. One caveat did, and it is the kind that wastes an
evening if it is not written down.

**Do not check whether a job is mirrored by searching the API payload for its name.**

```powershell
# WRONG — this answers "no" whatever the truth is.
curl -s http://127.0.0.1:5002/api/v1/schedule-status | findstr SPY_REFRESH_PM
```

`/api/v1/schedule-status` does not enumerate slots. Its keys are `freshness`, `active_window`,
`next_scheduled_job`, `incidents` and so on — a slot id appears only if it happens to be the
next job or an incident. Searching that payload for a job name reports "missing" for every job
that is present and working. That mistake stood in two stage reports before it was caught.

**Ask the table instead:**

```powershell
python -c "import os; os.environ['RAITS_TRACK1_ONLY_SHADOW']='1'; import datetime as dt; from monitor.backend import schedule_status as ss; print([s['id'] for s in ss._scheduled_slots_for(dt.date.today())])"
```

or check the scheduler's own inventory, which is the other half of the same question:

```powershell
python -c "from global_index import track1_slots as t; ids=t.scheduler_slot_ids(track1_only=True); print(len(ids), 'spy_refresh_pm' in ids)"
```

The two must agree. A job in the scheduler and not the mirror is a phantom overdue row every
day; a job in the mirror and not the scheduler is an alarm that never clears.

### And a note for anyone reading a lateness figure

`get_schedule_status` uses the **running scheduler's start time** to decide whether a slot is
judgeable at all. A slot that fell before the process existed is *pre-start*, not overdue —
the same rule the Track 1 audit applies. So after any restart, that day's earlier slots stop
being reported as late. That is correct, and it is also why a re-derived audit of a restarted
day reads `window_closed_before_scheduler_start` rather than `FAIL`. Read the records written
during the day, not a re-derivation after a restart.

---

## Appendix addendum — the paper readiness gate, and a correction (Stage 5S, 2026-08-25)

### The correction first

This runbook has read, throughout, as though closing the blockers is what stands between the
shadow route and paper trading. **That is not true, and the gap is larger than a command.**

`run_live_day_track1.run_shadow` constructs `NoOrderBroker()` unconditionally — its
`send_order` raises — and `IBKRBroker` is **never constructed anywhere in that module**. Arming
the gate today changes exactly two things: the decision mode recorded in the evidence, and
whether the freshness gate binds. **No code exists in this route that can place an order.**

So the sequence below gets you to a gate that is open. Walking through a door still requires
the door. Building and proving an order path is a project, and it is not written yet.

### The gate now has an EVIDENCE half

Until 2026-08-25 every condition was about authorisation: B1 is a decision recorded on disk,
the live-frame gate measures wiring, `TRACK1_ORDERS_APPROVED` is an approval and
`--allow-orders` is a request. Nothing asked whether the route had ever worked. Measured: with
a confirmation file releasing B1 and **zero** judgeable shadow days, `may_enable_orders()`
returned **True**.

A new blocker, `PAPER_SHADOW_EVIDENCE`, closes that. It **cannot be signed, only earned**:

```powershell
python -m global_index.track1_paper_readiness
```

| requirement | value |
|---|---|
| judgeable days | **5** |
| FAIL days allowed | **0** |
| WARN days allowed | **1** |
| every sleeve PASSED at least once | all four |
| newest qualifying day | within **21 days** |
| p95 | under **300 s** throughout; 240 s is the target and costs the WARN allowance |

Absence never counts as a pass — a missing audit file is a day nobody watched. The qualifying
days are the most RECENT judgeable ones, so the gate **closes again** if the evidence goes
stale, and a check that cannot run fails closed.

The five numbers are judgement calls and live in one named block in
`global_index/track1_paper_readiness.py`. Move them there and nowhere else.

### The sequence, corrected

```powershell
# 1. EVIDENCE — every check must read PASS. Cannot be signed, only earned.
python -m global_index.track1_paper_readiness

# 2. DECISION — record the B1 choice. Written by a person, never by a script.
#    global_index/track1_go_live_confirmation.json
#      {"schema_version": 1, "confirmed_by": "<name>", "confirmed_at": "<YYYY-MM-DD>",
#       "legacy_retired_confirmed": true}          (or separate_account_confirmed)

# 3. CONFIRM the registry agrees.
python monitor\ops.py status          # expect orders_possible=True, track1_blocking=[]

# 4. THE ORDER PATH ITSELF — does not exist. See the correction above.

# 5. Only then, per invocation and NEVER from the scheduler:
#    TRACK1_ORDERS_APPROVED=1  and  --allow-orders
```

### What to check after each judgeable window

```powershell
python -m global_index.track1_shadow_audit --latest --all --dry-run
python -m global_index.track1_paper_readiness
```

The sleeve must reach **PASS**, not `NOT_ENOUGH_DATA_YET` — the latter means its window closed
before the scheduler was up and nothing was judged. Then the readiness count should move by one.
If it does not, read which check refused before assuming the day was good.
