# Track 1 blocking ledger

> **Updated 2026-08-23 (Stage 4C).** Stage 4B put a gate back because the route had no way to
> obtain a live bar, so the join it had been given guarded nothing. Stage 4C built that way and
> the gate **opened by measurement**: there is now exactly one place on the route where live
> bars arrive, and every branch of it ends in the checked join. **Only B1 blocks.** The gate is
> not deleted and not signed off — it is still measured on every read, and it shuts again by
> itself the day a fetch appears that skips the join. Sections are updated in place — this is a
> live ledger, not a record of a moment.

**Generated from `global_index/track1_gates.BLOCKERS`, not written beside it.**
`scratch/test_track1_stage3b_blockers_20260822.py::test_ledger_matches_the_registry_exactly`
compares this file's JSON twin against the registry byte for byte. If they ever disagree,
regenerate — do not edit.

**Three statuses, and only three.** There is deliberately no OPEN: "open" is where a blocker
goes to be forgotten, because nothing enforces it and nobody has to do anything about it.

| status | meaning |
|---|---|
| `CLOSED` | the thing that was missing now exists, with a test that goes red when it is removed. It no longer blocks orders. |
| `USER_DECISION_GATE` | the code is done; what is missing is a decision only the project owner can make. It blocks orders, and only an explicit confirmation on disk releases it. |
| `MEASURED_GATE` | something is missing from the **code**, and whether it is still missing is decided by a measurement run on the spot. No confirmation flag can release one — that is enforced by the registry's own structural check. |

**The gate is code.** `global_index/run_live_day_track1.OrderGate` asks the registry, and the
registry asks `track1_go_live_confirmation.json` — which this build does not create, which is
schema-checked on every read, and which is refused whole if any part of it fails validation.

---

## Summary

| # | blocker | status | blocks orders | released by |
|---|---|---|---|---|
| 1 | `B1_broker_account_or_legacy_retirement` | **USER_DECISION_GATE** | yes | `legacy_retired_confirmed` **or** `separate_account_confirmed` |
| 2 | `B3_intraday_freshness` | **CLOSED** | no | — |
| 3 | `SLEEVE_normal_r4` | **CLOSED** (Stage 4) | no | — |
| 4 | `SLEEVE_nkd_mnkd` | **CLOSED** | no | — |
| 5 | `SLEEVE_calm_a` | **CLOSED** (Stage 4) | no | — |
| 6 | `SLEEVE_stress_mnq` | **CLOSED** | no | — |
| 7 | `CHECKPOINT_bootstrap_under_track1_params` | **CLOSED** | no | — |
| 8 | `WIRING_scheduler_dashboard_paper` | **CLOSED** (Stage 4) | no | — |
| 9 | `LIVE_FRAME_ADAPTER_VERIFICATION` | **MEASURED_GATE** (Stage 4C: released) | not while the measurement passes | nothing signable — only the wiring measurement |

**7 closed with code and tests. 1 released by measurement. 1 held by a decision. None prose-only.**

> **B1 is the only thing holding the order gate shut.** A valid confirmation file plus
> `TRACK1_ORDERS_APPROVED=1` arms it — two independent factors, and a test asserts that neither
> alone is enough.
>
> The measured gate is released, not closed, and the difference is the point. It is re-measured
> on every read, so a fetch added tomorrow that does not join through the guard shuts the route
> again without anyone noticing it needed to. A test holds the measurement shut and requires
> every confirmation flag together to fail, so it can never become signable by accident.

---

## 1. `B1_broker_account_or_legacy_retirement` — USER_DECISION_GATE

**What is true.** `IBKRBroker.__init__` takes `host`, `port`, `client_id`, `bar_duration` and
no account. `get_positions()` reads `ib.positions()` unfiltered and `get_equity()` reads
`NetLiquidation` unfiltered, so one Gateway login is one position book. A legacy LONG 1 beside
a Track 1 SHORT 1 on the same symbol reconciles as broker × 0 against two file rows — that is
`B3 MISMATCH`, and it halts entries for **both** routes. It is the same mechanism that put the
legacy `STRESS_MID` cron behind `if False:`. A different `client_id` does not help: it decides
who may cancel an order, not whose positions are counted.

**Why code cannot close it.** Neither an account nor a retirement can be conjured by a test.

**The decision.** Retire legacy first and let Track 1 be the sole route on the existing account
— the stated end state and the cheaper of the two — or fund a dedicated IBKR account. Record it
in `track1_go_live_confirmation.json`.

**The runbook:** `docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md`. Eight preconditions, eight
ordered steps, and a rollback.

---

## 2. `B3_intraday_freshness` — CLOSED

**What was missing.** Legacy's freshness gate is the 13:45 ET pre-flight flag, which works only
because every legacy window opens after 13:45. Calm A (10:00) and Stress (10:35–12:30) open
before it. Stage 3 encoded the D-1 contract for the historical inputs and reported the intraday
source as UNVERIFIED, deliberately, because nothing could see it.

**What closes it.** `global_index/track1_intraday.py` validates a bar frame against a declared
requirement per sleeve and fails closed on **missing, not-a-frame, wrong timezone, duplicate
timestamps, out-of-order, missing session, partial coverage, a hole in coverage, stale,
too-early, too-late, decision bar absent** and **window unobserved**.

The requirements, stated exactly rather than implied:

| | Calm A | Stress-MNQ |
|---|---|---|
| today's span the decision reads | 09:30–10:00, contiguous | 09:30–10:30, contiguous — that IS the detector's input |
| decision bar | 10:00 must be present; its OPEN is the entry | none — entry is a break inside the window |
| clock | at or after 10:00, and not after 10:00 | at or after 10:35, at or before 12:30 |
| prior session | 09:30–16:00 complete — the gate reads it | not required |
| observation | — | the window ledger must not report `incomplete` |

The validator is **source-agnostic** — it takes a frame and an instant — so it is real gate
logic rather than a promise about a source that does not exist yet, and the live adapter will
not have to bring its own copy.

**Two deliberate refusals rather than repairs.** A duplicated timestamp survives sorting and
the last one wins on a reindex — which is how 1,050 of 1,590 NKD live bars once overwrote
frozen history with a 13-hour clock error. And a tz-aware frame in the wrong zone is refused,
not converted: converting is how a frame ends up correct by accident and wrong the next time
the offset moves.

**Tests:** 11 fail-closed cases for Calm A, 6 for Stress, one passing case each, plus a test
that an unsupplied window-observation check reports "did not run" rather than passing.

---

## 3. `SLEEVE_normal_r4` — CLOSED (Stage 4)

**Closed by promotion, not by accepting isolation.** `global_index/track1_normal_r4.py`
generates the sleeve from bars and reproduces the committed rows **exactly on all three
windows — 980 on floor, 136 on vault2025, 107 on vault2026: 1,223 rows, per instrument, row
for row.**

**And it replaces nothing.** The scratch path rebound five production symbols and mutated
`trend_follow.DEFAULT_CONFIG` for the duration of a run. A test now asserts by **object
identity** that a run leaves all five and the config untouched — identity rather than
equality, because the scratch path restores them in a `finally` and would pass an
afterwards-only check.

Where each patched thing went: the class-level `generate_signal` replacement became a caller
that gates the strategy's own return value; `force_all_bars_gappable` became a post-processed
**copy** of the cache; the `DEFAULT_CONFIG` mutation became a local constant; `run_loop` became
a day loop carrying only the branches this sleeve reaches. The two context filters were
**promoted** — moved into `global_index/track1_normal_filters.py` — and a test requires the
promoted copy and the scratch original to return the same verdict for every 5-minute bar of a
real instrument, because the scratch library's own header says there is one implementation on
purpose.

**Two things had to be measured, and each cost a first attempt:**

* **same-day re-entry.** A session that already exited is rescanned over the window *after*
  that exit rather than served from the signal cache. MES exits MAX_HOLD at 09:30 on
  2026-01-26 and re-enters at 15:20 the same session; without it the port produced 20 trades
  where the record has 22.
* **the daily-ATR warm-up.** A day with no usable daily ATR is dropped from the cache. It bites
  at the start of a clipped window: without it, vault2025 gained trades on 2025-01-02 and
  2025-01-10 that the record does not have, and the record's first trade is 2025-01-21 — about
  fourteen sessions in, which is exactly the warm-up.

## 4. `SLEEVE_nkd_mnkd` — CLOSED

The sleeve **is** `futures.swing_tf.SwingTFEngine` at ema 10 / chandelier 2.5 / hold 5 with
`RegimeLabels(lag_days=1)` — production code today, unchanged by Track 1. Since Stage 4 its
rows are produced by the promoted generator at `ema_period=10` with the R4 context filter off,
from bars rather than from a frozen table, and they still reproduce exactly: 228 / 31 / 26.

Its route identity differs from the Stage 2B bootstrap only in **rendering** — measured field
by field, **zero** strategy differences — so it resumes once the bootstrap is regenerated,
which blocker 7 does.

---

## 5. `SLEEVE_calm_a` — CLOSED (Stage 4)

**Closed by implementing the detector, not by accepting the frozen list.**
`global_index/track1_calm_a.py` computes the setups from bars and reproduces the frozen list
**exactly on all three windows — 421 of 421 rows.**

Matching the same DAYS could happen with a slightly wrong feature and a compensating
threshold, so the test also matches the four **recorded feature columns** —
`gap_from_prev_rth_close`, `prev_close_loc`, `prev_rth_ret`, `open_loc_prev_range` — to 1e-9.
A guard test fails the run if the detector path so much as opens the CSV.

**Two conventions were read out of the record rather than guessed**, and each was found by a
divergence rather than by reading:

* **the prior session's RTH window ends at 15:59, not 16:00.** One bar. For MNQ on 2018-01-04
  the frozen row implies a prior close of 8724.50; [09:30, 16:00] closes at 8725.75 and
  [09:30, 15:59] at 8724.50, which moves close-location from 0.3675 to 0.3248 — across the 1/3
  threshold. That single bar decides whether the day sets up.
* **a session counts only if it RAN TO that close.** The record's own `prev_session_day` column
  names it four times: 2019-12-26 goes back to 2019-12-23 skipping Christmas Eve, 2020-12-28 to
  2020-12-23 likewise, 2023-11-27 to 2023-11-22 skipping Black Friday, 2025-02-18 to 2025-02-14
  skipping Presidents' Day. A calendar was tried first and is the wrong tool:
  `raits.live.trading_calendar` calls Christmas Eve and Black Friday trading days, which they
  are — the exchange is open. What this detector cannot use is a session with no 15:59 bar,
  because its close and range would then be measured at 13:00 and mean something else. With the
  calendar rule floor lost 5 rows and gained 2; with the ran-to-close rule it is exact.

**The thresholds were read off the artifact, not fitted:** `prev_close_loc` tops out at exactly
0.333333 and `prev_rth_ret` at exactly 0.000000 across all 421 rows, and the audit states the
gap filter verbatim as `current_rth_open / prior_rth_close - 1 >= -0.010`.

## 6. `SLEEVE_stress_mnq` — CLOSED

Fully computed from bars by a rule, start to finish: `load_window` → `build_day_cache` →
`build_rule_with_levels(make_rule(Scenario('mnq_only_g3_q7', ('MNQ',), 7)))`. No frozen trade
table anywhere in the chain, no monkeypatching of production modules, and quantity 7 travels
on the rows themselves.

Its one side effect is scoped and reversed in a `finally` — it sets `SETUPS` to `("10:30",)`
for the call. That is a different thing from replacing a production function for the duration
of a run.

Confirmed **not** `futures/stress_liquidation_1020.py`, which is a different 10:20 candidate
that says of itself that it is deliberately not wired. A test asserts both halves of that.

---

## 7. `CHECKPOINT_bootstrap_under_track1_params` — CLOSED

`global_index/track1_bootstrap.py` writes two artefacts, because Stage 2C established that the
per-instrument checkpoint is not enough — the **book** carries more across a day boundary, and
each carried value changes which trades are *admitted*:

    open positions with cluster and risk   the cap gate reads them
    equity                                 drives the breaker
    peak_equity                            kept across days; drawdown measures from it
    day_start_equity                       the -4% daily rule measures from it
    cur_day                                decides when start_day() re-bases that rule
    booked                                 a double-settlement COUNTER, never an input

**The cut is an instant, never a day.** `restore()` refuses a bootstrap with no `cut_instant`,
because a day-keyed cut is not a prefix of the event sequence — on the floor window it left two
events on 2022-01-10 in neither half and the resumed book skipped a Stress override.

**Measured:** resume is exact on both a bare-date cut and an explicit mid-day instant — 91
events split 39 + 52, equity identical, the same two positions open at the end. The Stage 2B
file is still refused with `params_mismatch`, and the test proving it is kept.

**And the thing Stage 2C could not prove is now proved.** Stage 2C reported honestly that two
mutations — a carried position in the wrong cluster, and its risk multiplied by twenty — would
not make the comparison diverge, and concluded that on its window the fields were not shown to
be load-bearing. Measured again here by sweeping cuts instead of picking one, the reason turns
out to be **the cut, not the field**.

A carried position's `cluster` and `risk_dollars` are read by exactly one thing: the cap gate,
when a same-cluster candidate arrives *while that position is still open*. Stage 2C placed its
cuts to make the breaker's peak bind — a few sessions before the deepest drawdown — and at
those instants no same-cluster candidate followed before the carried position exited. Measured
directly at one such cut: both carried positions had **zero** same-cluster candidates before
they exited. Carried, restored, never consulted.

With a cut that does consult them, every carried field diverges, on all three windows:

| carried field | vault2026 | vault2025 | floor |
|---|---|---|---|
| `cluster` | 2026-01-26 14:30 | 2025-01-21 14:15 | 2018-10-31 14:35 |
| `risk_dollars` | 2026-01-26 14:30 | 2025-02-03 15:25 | 2018-02-22 14:45 |
| `day_start_equity` | 2026-01-26 14:30 | 2025-02-05 14:20 JST | 2018-02-22 14:45 |
| `equity` | 2026-06-29 14:55 | 2025-05-22 14:20 | any floor cut tested |
| `peak_equity`, `positions` | any cut carrying anything | " | " |

`equity` needed its own hunt: resetting it to the account base only bites once the book has
grown enough that the reset manufactures a drawdown crossing a breaker threshold.

The condition is now in code — `track1_bootstrap.binding_cuts()` returns the instants where a
carried position's cluster is consulted again — so the next mutation test picks a cut that
*can* bind instead of hoping an arbitrary one does. `booked` remains a double-settlement
counter and is correctly inert.

---

## 8. `WIRING_scheduler_dashboard_paper` — CLOSED (Stage 4)

`run_scheduler.make_scheduler` takes `track1_shadow` (CLI `--track1-shadow`), **off by
default**. Off registers the same 60 jobs it always has, with `STOP_REPAIR_1220` still present
and the legacy argv byte-identical — all three asserted by test. On, it adds the 25 Track 1
slots and extends `_ENTRY_WINDOWS` with `((10,35),(12,30))`, so the 12:20 sweep stops running a
B3 reconcile inside the Stress window.

The dashboard mirror gates on `RAITS_TRACK1_SHADOW=1` and makes the same subtraction from the
same constant — `run_scheduler._TRACK1_STRESS_WINDOW`, asserted equal to
`track1_slots.REQUIRED_ENTRY_WINDOW` and to `schedule_status.TRACK1_STRESS_WINDOW`, so the
window exists once rather than three times. The parity check now flips **both** sides together,
is green in both modes, and is still shown able to go red.

A Track 1 slot calls `run_live_day_track1` with no `--allow-orders` and no broker port.

**Scope, stated plainly: this closes the WIRING, not the running of it.** No scheduler was
started and no Track 1 slot has ever fired. What it means is that enabling shadow is now one
flag on two sides rather than an unwritten change.

The **paper-output policy** is unchanged and still asserted per channel: runner events share a
file with a route field; `trade_log.jsonl` stays separate until `paper_evidence_reader` can
split on route; live state is route-scoped; slot timing and window coverage already carry route.

---

## 9. `LIVE_FRAME_ADAPTER_VERIFICATION` — MEASURED_GATE, released (Stage 4C)

**What was missing, and what changed.** Stage 4B built a join that could not corrupt history,
and then measured that nothing on the route could obtain a live bar to join — so the guard
guarded nothing, and every Track 1 number in existence had come from a frame that was already
complete. Stage 4C built the missing half. There is now exactly one place on the route where
live bars arrive, and every branch of it ends in the checked join, including the branches where
the provider offers nothing at all. That last part is not pedantry: an early return on "no bars
today" is precisely how an unchecked frame reaches a sleeve, and there is a test that counts the
calls rather than trusting the reading.

**The step the join deliberately refuses to take.** The two halves are on different clocks, and
not by accident — it is the contract on both sides. History is a parquet file whose stamps are
UTC, read as New York, and read once more as Tokyo for the Nikkei sleeve, because that is the
session it trades in. The broker path returns bars already moved to New York and then stripped
of their zone. So something has to convert, and the join refuses to be that something: a
converter inside it would make a wrongly-clocked frame look plausible, which is exactly how the
original corruption passed every check that existed. The conversion is therefore explicit, it
happens in one place, and it takes its target from the frozen frame itself rather than from a
table that could disagree with the file.

**Two failures that only appeared once bars actually moved.** Both were found by running the
thing, not by reading it.

*Backwards.* A mis-converted session lands on timestamps history already owns. The join trims
those away and keeps history — safe, and silent, and silence is what let the original error run
for as long as it did. So the overlap is now compared instead of discarded: where both halves
describe the same instant they must report the same price, because two readings of one
instrument at one moment cannot differ. Reproducing the Nikkei error is refused, and the largest
disagreement it reports is about a thousand points — the same magnitude the real corruption had.

*Forwards.* The same clock error in the other direction puts every bar in empty space past the
end of history. Strictly newer, unique, in order, matching columns: every rule the join has,
satisfied, and it appended the lot and reported success. Nothing in the join can see this. What
catches it is a fact about fetching rather than about prices — a fetch cannot return bars from
after the moment it was taken — so the last joined bar is checked against the instant it was
asked for, with no tolerance to tune.

**And the thirteen hours are not thirteen hours.** Japan does not keep summer time and the
United States does, so the same mistake is worth thirteen hours from March to November and
fourteen for the rest of the year. Anything that hard-coded thirteen — a check, a tolerance, a
test — would be right for about eight months a year and quietly wrong for the other four. Both
sides of that boundary are pinned.

**What is still not proven, and cannot be here.** That any of this is correct on a real trading
day. No day has been run and no broker has been connected. What is proven is narrower and
checkable: cut a real frame, hand the tail back as though it were live, and the join gives the
original back bar for bar — for the S&P and for the Nikkei — with the trend sleeve and the Calm
detector reaching identical decisions, and with both same-session gates behaving identically on
a session that stops mid-flight. There is also a stated limit: a live half several days long,
shifted forward by less than its own span, is caught by neither check. A real session fetch is
hours, so a whole-zone error is always larger than the span — but a caller that starts handing
over multi-day live halves is outside what has been shown, and that is written into the module
and into a test by name rather than left to be discovered.

**How it could shut again.** The measurement runs on every read. It parses the code of every
Track 1 module found on disk — discovered, not listed, so a file added tomorrow is included —
and asks whether anything obtains live bars and whether everything that does joins through the
guard. It reads parsed code rather than text, because a detector in this repository once asked
whether a line contained the word "python" and turned every stack trace into a phantom job.
Add a fetch that skips the join and this gate closes by itself, with no one needing to remember.

---

## What would open the route

**One thing, and it is a decision.**

The live bar path that Stage 4B was waiting for was built in Stage 4C, and that gate opened by
measurement rather than by anyone signing for it. It is still measured on every read, so it is
not a box that has been ticked — it is a condition that currently holds.

What is left is B1, unchanged:

```json
{
  "schema_version": 1,
  "confirmed_by": "<name>",
  "confirmed_at": "<YYYY-MM-DD>",
  "legacy_retired_confirmed": true
}
```

or `separate_account_confirmed` instead, plus `TRACK1_ORDERS_APPROVED=1` in the environment.
Two independent factors, deliberately: one flag on a command line is never enough to reach an
exchange. A test asserts both halves — the file alone does not arm the gate, and both together
do. A third test holds the wiring measurement shut and requires the same two factors to fail,
so the measured gate cannot quietly stop mattering.

**This is not a statement that Track 1 is ready to trade.** The bars are wired and the join is
guarded; no live day has been run, no broker has been connected, and the decision below is a
real one about which account holds which positions.

Stage 4 **removed three confirmation flags** — `normal_generator_isolation_accepted`,
`calm_a_detector_accepted_frozen` and `scheduler_wiring_approved` — because the blockers they
existed to release are closed. Gone rather than left unused: a flag that releases nothing is a
flag somebody will one day set and believe something happened. The confirmation file refuses
unknown keys, so a file naming one of them now fails validation, which is the correct answer.

---

## Added 2026-08-25 (Stage 5S) — `PAPER_SHADOW_EVIDENCE`

**Status:** `MEASURED_GATE` · **blocks orders:** yes · **cannot be signed, only earned**

Every condition on this gate used to be about AUTHORISATION and none was about EVIDENCE. B1 is
a decision recorded on disk. `LIVE_FRAME_ADAPTER_VERIFICATION` measures the code's wiring.
`TRACK1_ORDERS_APPROVED` is an out-of-band approval, and `--allow-orders` is a request.
Meanwhile `track1_shadow_acceptance` computes, every single day, whether the route actually did
what it was supposed to — and nothing that decides whether orders may be sent had ever read it.

Measured on 2026-08-25: with a confirmation file releasing B1 and **zero** judgeable shadow
days, `may_enable_orders()` returned **True**. It now returns **False**.

`PAPER_SHADOW_EVIDENCE` reads the audit records the route writes to its own durable runtime
directory and asks for a shadow period that went well:

| | requirement | where it lives |
|---|---|---|
| judgeable days | `REQUIRED_JUDGEABLE_DAYS` = 5 | `track1_paper_readiness.py` |
| FAIL days allowed | `MAX_FAIL_DAYS` = 0 | same |
| WARN days allowed | `MAX_WARN_DAYS` = 1 | same |
| evidence age | `MAX_EVIDENCE_AGE_DAYS` = 21 | same |
| every sleeve PASSED at least once | `REQUIRED_SLEEVES` | same |

Those five numbers are judgement calls rather than derived quantities, and they are gathered in
one named block so they can be moved deliberately in one place. Moving them changes what
"ready" means and nothing else.

**Absence is never a pass.** A day with no audit record is a day nobody watched, not a day that
went well. A missing directory, an unparsable line, a `NOT_ENOUGH_DATA_YET` verdict and a
record for another route all count against readiness, and a check that cannot run at all fails
closed — `scheduler_processes()` returning `[]` for "I could not tell" already cost this project
six entry slots, and this is the one place where repeating that would OPEN a gate.

**Staleness is the same problem wearing a date.** Five clean days in August do not make December
ready, so the qualifying days must be the most recent judgeable ones and the newest must be
inside the age limit. The gate can close again after it has opened.

To read it:

```powershell
python -m global_index.track1_paper_readiness
```

It can only refuse. It cannot arm anything, and it says nothing about the broker question B1
holds.

---

## Added 2026-08-26 (Stage 5ZL) — `REGIME_LABEL_VERIFICATION`

**Status:** `MEASURED_GATE` · **blocks orders:** yes · **cannot be signed, only earned**

*Recorded here 2026-08-26 (Stage 5ZR). It had been live since Stage 5ZL and this document did
not mention it — a ledger that omits a gate the operator is currently held by is worse than no
ledger, because it is read as complete.*

Which sleeve is allowed to trade is decided from HMM regime labels, and the check that those
labels have not moved **could not report a failure**. It returned a COUNT, and returned `0`
from four places that had verified nothing: no engine, unreadable inputs, a raising labeller,
and no overlapping dates — that last one printing *"HMM stable"* having compared zero labels.

Zero is also what a clean run returns. So *"I could not check"* and *"I checked and it was
fine"* were the same number, the one call site discarded it anyway, and the process exited 0
into a scheduler that throws away a clean child's output. A drift was invisible end to end.

The gate reads the recorded status and opens **only on PASS**. `DRIFT` and `UNKNOWN` both hold
it and are reported separately: a drift is a finding about the data, an unknown is the absence
of a finding. No record at all is `UNKNOWN` — a check that never ran is not a check that
passed.

**Scope:** it holds the PAPER gate. It deliberately does not block shadow slots, and the 13:45
pre-flight deliberately does not run strict, because a verification that could not run must not
skip a trading day.

```powershell
python -m global_index.update_spy_csv --csv spy_daily_live.csv --verify-strict
```

The scheduler's 16:20 job records it daily.

---

## Amended 2026-08-26 (Stage 5ZQ) — `B1` now needs a decision AND a proof

Section 1 above describes B1 as it stood: released by `legacy_retired_confirmed` or
`separate_account_confirmed`, and by nothing else. **That is no longer the whole rule.**

A person writing one of those flags asserted a fact about an IBKR account, and nothing in the
system had ever asked the account. Precondition 7 of the switch-over runbook — *"legacy is flat
AT THE BROKER, not only on disk"* — had never been checked by anything.

B1 now reads:

```text
released = signed AND (the B1 measurement passes OR an explicit waiver is set)
```

Strictly tighter: every path that opened it before still needs the signature, and now needs the
proof as well.

| | |
|---|---|
| the measurement | `legacy_broker_flat` — reads the recorded B1 audit; PASS only |
| how to record one | `python -m global_index.b1_audit --broker ibkr --record` |
| how long it counts | 24 hours, then the gate closes again on its own |
| the waiver | `b1_measurement_waived` — releases NOTHING alone, and is refused without a `note` saying why the account could not be asked |

Measured 2026-08-26 06:15 ET: legacy book 0, Track 1 book 0, broker positions 0, working
orders 0, orphans 0 — the measured half passes. The decided half is still empty, and Stage 5ZR
recorded why: legacy is **dormant, not retired** (`track1-only-shadow` registers 0 legacy entry
jobs, the default mode registers 45 — one command-line flag apart), and there is one account.


---

## Added 2026-08-31 (Stage 5ZZZ-AZ) — `FINAL_BAR_DIVERGENCE_OBSERVED`

**Status:** `MEASURED_GATE` · **blocks orders:** yes · **cannot be signed, only observed**

Every sleeve family's last slot fires at `:55` on the session clock, which is the moment the
window's final bar OPENS. The detector therefore reads a bar seconds old, and
`volume_resume_surge` requires volume ABOVE a ten-bar average — so that bar fails, and no later
slot exists to read it complete. The backtest reads the same bar whole.

Measured on NKD 2026-08-31, slot 02:55: the 15:55 Tokyo bar was evaluated with volume **0**
against a ten-bar average of **32**.

Size, on the committed rows:

| | measured |
|---|---|
| orders signalled on the final bar | 13 of 1,223 — **1.06%** |
| P&L lost when the bar is withheld from all three windows | **−$5,934.85 = −12.02%** |
| why the second is larger than the first | the orders that fill the space left behind lose money |
| would a 15:59 slot fix it | no — the closing minute alone carries **56.4%** of that bar's volume, so only **6 of 13** clear the threshold four minutes in |

**Why it blocks.** Not because 12% is at risk, but because nobody knows *which* 12% it is.
Either live silently gives that up, or the baseline sits that far above anything live can reach
and every comparison against it misses forever with no visible cause. Both are unacceptable to
run orders under, and one observation separates them.

**How it opens.** A row in `global_index/track1_final_bar_observation.py`'s ledger, written by
a Normal session's final slot, saying whether its newest bar had closed. Nothing to sign:
`released_by` is empty, so no signature can open it. Absence is UNKNOWN, never a pass, and a
check that cannot run fails closed.

**Where the evidence lives, and why it moved (2026-08-31, Stage 5ZZZ-BD).** The first version
read the display-side diagnostics store and filtered reconstructions out. That broke the line
this repo holds by construction -- no gate, readiness check or acceptance judge may name the
module holding reconstructions -- and the test enforcing it walks three files and stops at the
first offender. Measured with the gate in place:

| file | mentions | state |
|---|---|---|
| `track1_gates.py` | 1 | BROKEN |
| `track1_paper_readiness.py` | 0 | **no longer reached** |
| `track1_shadow_acceptance.py` | 0 | **no longer reached** |

The alarm for three files had been left ringing for one, which is the same as switched off --
and the two it stopped covering are the ones that grade shadow days and gather evidence, both
running unattended every day. The evidence now has its own ledger, written only by the slot
path. A reconstruction cannot reach the gate because there is no path, not because a filter
turns it away.

**Scope.** It asks only that the behaviour be OBSERVED. It takes no view on the fix — adding a
`:00` slot, or removing the bar from the baseline, are both coherent, and both are the
operator's decision afterwards.
