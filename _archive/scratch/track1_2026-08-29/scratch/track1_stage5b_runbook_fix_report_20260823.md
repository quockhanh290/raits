# Stage 5B — fixing the instructions before anyone follows them

**2026-08-23 · runbook and tests only · no scheduler started, no IBKR connection, no order, no
dashboard write, no `STOP_TRADING`, no confirmation file, no commit.**

---

## Verdict: **RUNBOOK_FIXED_READY_FOR_MANUAL_STOP_TRADING_THEN_SHADOW_START**

All four Stage 5 defects are fixed and each is pinned by a test that goes red if the fix is
reverted. Nothing was executed: the next step is a human one, in this order — settle the
scheduler-down question, place `STOP_TRADING`, then start the scheduler with `--track1-shadow`.

What did **not** change: the gate state. No confirmation file, `self_check()` empty, and
`blocking()` still returns exactly `B1_broker_account_or_legacy_retirement`.

---

## 1. Exact runbook changes

### 1.1 The S4 template that the schema refused

**Was:** a five-flag template including `scheduler_wiring_approved`,
`normal_generator_isolation_accepted` and `calm_a_detector_accepted_frozen` — all removed in
Stage 4 when the blockers they released were closed. The file is refused *whole* on any unknown
key, so copying that template granted **zero** flags. The gate stayed shut and looked like a
code fault, at the one moment an operator is least equipped to debug it.

**Now:** exactly the keys the schema accepts.

```json
{
  "schema_version": 1,
  "confirmed_by": "<name>",
  "confirmed_at": "<YYYY-MM-DD>",
  "legacy_retired_confirmed": true,
  "note": "<why, in one sentence>"
}
```

with `separate_account_confirmed` named as the path-B substitution, a verify snippet, and the
history of the three removed flags kept **in prose only** — worth remembering, impossible to
copy by accident.

Added above it, because ordering was the other half of the problem:

> **Do not write this file yet.** It is the last thing to create, not the first. Every check
> above it must have passed first — the broker reporting flat, no working STP left, and an
> operator who has decided.

### 1.2 `STOP_TRADING` moved ahead of every start

A new **section 2** now sits before all the steps, holding two things that must happen first.

**S0a — find out why the scheduler is down.** It was running days ago; it is not now, and no
record says who stopped it. Deliberate means the drain is partly done; accidental means the
system has been silently not trading since **2026-08-21**, which is its own incident. A clock
is already running either way: nothing refreshes the SPY CSV while the scheduler is down, and
past five business days the G1 hard gate blocks entries on **both** routes.

**S0b — the kill switch goes in before any start.** With the measured table:

| | jobs | Track 1 slots | legacy jobs | legacy entry slots |
|---|---|---|---|---|
| shadow OFF | 60 | 0 | 60 | 23 |
| shadow ON | 84 | 25 | **59** | **23** |

`--track1-shadow` adds 25 jobs and removes exactly one. **Every legacy entry slot survives.**
So starting the scheduler in shadow mode resumes legacy trading, and if the intent is to retire
legacy, the kill switch has to already be on disk when that start happens. The order is stated
outright: `STOP_TRADING` → start → watch → everything else. S1 now cross-references this for the
scheduler-is-down case.

### 1.3 Precondition 4 is now checked by effect

**Was:** "`_ENTRY_WINDOWS` contains `((10,35),(12,30))`" — a local variable inside
`make_scheduler`, so the check as written raises `AttributeError`.

**Now:** the row reads "no stop-repair sweep lands inside the Track 1 Stress window", and the
runbook carries a snippet that builds both schedulers without starting either:

- `stop_repair_1220` present with shadow off, absent with it on, and **nothing else removed**;
- 24 Stress slots spanning `track1_stress_1035` … `track1_stress_1230`, plus `track1_calm_1000`;
- the three copies of the window — scheduler, slot table, dashboard mirror — all equal, and
  parity true in both modes.

The name `_ENTRY_WINDOWS` survives in exactly one place: the paragraph explaining why it cannot
be used. A test pins that it is the only occurrence and that it says so.

### 1.4 Precondition 2 no longer claims a live decision

**Was:** one row, "the four sleeves can produce a live decision", checked by `readiness()`
returning an empty `blocked` list. Those measure different things, and the row read as
"Track 1 can trade".

**Now:** two rows.

| | claim | today |
|---|---|---|
| 2a | every sleeve's generator is promoted, readiness metadata green | **PASS** |
| 2b | Track 1 actually produces a live decision | **FAIL** |

with a paragraph saying what 2b still needs — today's regime label, a cost object, Calm A's true
stop-risk sizing — and the sentence the whole split exists for: *until 2b passes, the honest
statement is "the sleeves are promoted", never "Track 1 can trade today".*

### 1.5 Preconditions 5 and 6 marked expected-to-fail

A status table now gives every precondition's state as audited, and says plainly that 5 and 6
**are expected to fail before the first shadow run** — there is no coverage file because no
window has been watched, and no checkpoint because no Track 1 slot has fired. They turn green by
running the shadow scheduler: *starting is what fixes them.*

### 1.6 Local flat is not broker flat

Precondition 7's row now reads "legacy is flat — **at the broker**, not only on disk", and adds
the orphan-STP condition. A new block states that legacy is not flat until IBKR has been asked,
and that neither the broker half nor the orphan-stop check has ever been run. S3 gains a warning
about how to read a broker screen: the account's last-seen net liquidation was far larger than
this system's equity, so **"no position" must mean no position on MES / MNQ / MYM / M2K / MNK,
not an empty account.**

---

## 2. Tests

New: `scratch/test_track1_stage5b_runbook_fix_20260823.py` — **22 passed**.

| suite | result |
|---|---|
| Stage 5B runbook fix (new) | **22 passed** |
| Stage 4C live source | **46 passed** |
| Stage 3B blockers | **72 passed, 1 skipped** |
| scheduler heartbeat + dashboard snapshot + log hygiene | **30 passed** |

**`scratch/test_track1_stage5_preswitch_audit_20260823.py` does not exist.** Stage 5 was a
read-only audit and shipped a report and a JSON, not a test file. The available Track 1 suites
were run in its place, as instructed. `global_index/test_event_playback.py` was not run.

### These tests can go red

A document test that passes on any text is decoration, so each key assertion was mutated against
an in-memory copy and shown to fail: a removed flag put back into the template is refused by the
schema; the precondition table naming `_ENTRY_WINDOWS` again trips the table check; the ordering
sentence removed trips the ordering check; the promoted row claiming a live decision trips the
split check.

One probe bug worth recording: the first ordering mutation replaced case-sensitively while the
runbook says "before **ANY** scheduler start" and the test lowercases first — so the probe
reported a false negative on its own first run. Re-run correctly, the assertion goes red. The
test was right; the check of the test was wrong.

### An interaction worth knowing

Stage 3B has a test requiring `_ENTRY_WINDOWS` to appear *somewhere* in the runbook — written
when it was still used as a check. It still passes, because the explanatory paragraph mentions
it. The two tests are compatible and, together, pin something useful: the name must be present
**and** must be present only as an explanation of why not to use it.

---

## 3. The four questions, answered directly

| question | answer |
|---|---|
| Does the S4 template now pass the schema? | **Yes** — parsed from the runbook, written to a temp file, `load_confirmations()` returns no errors and grants `legacy_retired_confirmed`. The real file was not created. |
| Is `STOP_TRADING`-before-start now explicit? | **Yes** — its own section, ahead of every step, with the measured job counts and the stated order. |
| Is precondition 4 now effect-based? | **Yes** — no runnable check names `_ENTRY_WINDOWS`; the surviving mention explains why it cannot be used. |
| Does precondition 2 still overclaim? | **No** — split into promoted (passes) and produces-a-live-decision (fails), with the honest phrasing spelled out. |

---

## 4. What is still unknown

Fixing instructions does not create evidence. Four things remain open, and two of them cannot
be closed by anything this stage was allowed to do.

**Why the scheduler is down.** Unresolved, and it is the first question. If the stop was
accidental, the system has been silently not trading since 2026-08-21 — an incident in its own
right, and one worth handling before a route switch is layered on top of it.

**Whether legacy is flat at the broker.** Not checked. The local book has been empty since
2026-08-21, and that is not the same claim. Requires IBKR.

**Whether any orphan working STP remains.** Not checked. Requires IBKR. This is the one that
fills into a position nobody asked for.

**Shadow coverage and the Track 1 checkpoint.** Both still absent, both expected to be, and
neither can be produced by anything except running the shadow scheduler. Related: Track 1 still
cannot produce a live decision — `load_source("live").candidates()` raises — so the shadow
period is where that gets resolved too, not before it.

---

## 5. Next action

Unchanged from Stage 5, and now safe to follow as written:

1. Settle the scheduler-down question.
2. Decide B1 explicitly — path A or path B.
3. Place `STOP_TRADING` **before** starting anything.
4. Start the scheduler with `--track1-shadow` and let it accumulate coverage. Orders stay
   impossible: B1 blocks, `TRACK1_ORDERS_APPROVED` is unset, and no Track 1 slot passes
   `--allow-orders`.
5. Only then the broker checks, and only after those, S4.

**Not claimed anywhere:** that the system is ready for live orders, that legacy is flat at the
broker, or that Track 1 can take a live decision today.
