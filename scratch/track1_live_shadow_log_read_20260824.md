# Track 1 live-shadow — what actually happened today

**2026-08-24 ·** read-only. Scheduler and backend **not** started, stopped or restarted by this
work · no IBKR connection opened by hand · no order · no confirmation file · nothing written
under `global_index/track1_runtime/` · no audit run outside the scheduler's own · no commit.
The only files this session created are the two deliverables in `scratch/`.

**Three clocks.** The machine is in Calgary (MDT), the market runs on ET, and every scheduler
log line is stamped in **machine** time. **ET = log line + 2h.** Every time in this document
is ET unless it is quoting a raw log line.

---

## The headline

Two things were believed going in, and the logs say one of them is wrong in a way that
changes what to fix first.

**Believed:** the column mismatch is a Calm-slot problem; the Stress sleeve is fine.
**Measured:** the column mismatch is **universal**. It will hit every instrument on every
sleeve. The Stress sleeve only looks healthy because a *different* refusal fires one line
earlier and stops the slot before it ever reaches the splice.

That earlier refusal comes from a stale data file. So **repairing the data file will make the
Stress sleeve go silent** — twenty-four slots that currently write an honest refusal row every
five minutes would start crashing exactly the way the Calm slot did at 10:00. The repair
order is not a matter of taste.

---

## 1. Where things stand right now

| | |
|---|---|
| Scheduler | **pid 28696**, started **09:25:31 ET**, one instance, code not stale |
| Backend | **pid 11720**, port 5002 |
| Mode | **track1-only-shadow** |
| Jobs registered | 100 — 70 Track 1 slots, 11 Track 1 safety jobs, 5 audit jobs; 45 legacy strategy jobs deliberately not scheduled |
| Broker | connected, feed **fresh** (3.9s old) |
| Orders possible | **no** |
| Blocking | **B1** — broker account or legacy retirement |
| Arming factors | confirmation file absent · `TRACK1_ORDERS_APPROVED` unset · no `STOP_TRADING.track1` · no `runner.track1.pid` |

One thing on the dashboard reads worse than it is. `/api/v1/schedule-status` reports
`freshness: "stale"` with a state age of about eight hours. That field is about the **legacy**
slot-state file, which nothing is updating in track1-only mode. The broker feed it might be
confused with is fresh. Worth knowing before someone reacts to the wrong number.

---

## 2. Today, in order

Everything before 09:25 belongs to earlier scheduler instances.

| ET | Job | Outcome | Took | What it left behind |
|---|---|---|---|---|
| 02:00–02:58 | `NKD_NIGHT_0200…0255` (12 runs) | exit OK, each wrote one ERROR line | ~70s each | **legacy route**, not Track 1. The error is the 20-month-old HMM model (`fit_end=2024-12-31`) |
| 04:20 / 06:20 / 08:20 | `TRACK1_STOP_REPAIR_*` | completed OK | 1s / 1s / 6s | nothing — no book to repair |
| **09:25:31** | **scheduler start (pid 28696)** | track1-only-shadow | — | 100 jobs registered |
| 09:31 | `TRACK1_MAX_HOLD_EXIT` | completed OK | **1s** | nothing |
| 09:31 | `MAX_HOLD_EXIT` (legacy twin) | completed OK | 10s | — |
| **10:00** | **`TRACK1_CALM_1000`** | **exited with code 1** | 4s | **only a `window_open` line** |
| 10:10 | `TRACK1_AUDIT_ROSKA4_CALM` | completed OK | 1s | one audit row, verdict **FAIL** |
| 10:20 | `TRACK1_STOP_REPAIR_1020` | completed OK | <1s | nothing |
| 10:35 | `TRACK1_STRESS_1035` | completed OK | 3s | `window_open` + `slot_observed` |
| 10:40 / 10:45 / 10:50 / 10:55 | `TRACK1_STRESS_1040…1055` | completed OK | 3s / 3s / 5s / 3s | one `slot_observed` each |

Four kinds of writing, kept apart because they fail apart:

| | ledger row | timing row | explanation row | audit row |
|---|---|---|---|---|
| Calm 10:00 | **no** | no | no | — |
| Stress 10:35–10:55 | **yes, 5** | no | no | — |
| Audit 10:10 | — | — | — | **yes, 1** |

**Timing rows: zero everywhere. Explanation rows: zero everywhere.** Neither is an accident of
today; see §5.

---

## 3. Evidence by sleeve

| | NKD | Calm | Stress | Swing |
|---|---|---|---|---|
| Window | 01:10–02:55 | 10:00 | 10:35–12:30 | 14:05–15:55 |
| Expected slots | 22 | 1 | 24 | 23 |
| Observed | **0** | **0** | **5** | 0 |
| Missing | 22 | 1 | 19 *(not yet due)* | 23 *(not yet due)* |
| Timing rows | 0 | 0 | 0 | 0 |
| Explanation rows | 0 | 0 | 0 | 0 |
| Audit | never fired | **FAIL** | due 12:40 | due 16:05 |
| Reason codes | — | `coverage_unobserved`, `missing_slot_ids`, `no_timing_records` | `overlap_disagreement` ×5 | — |

**NKD needs saying plainly:** its window closed at 02:55, seven hours before this scheduler
existed. Its audit job runs at 03:05 and never fired either. The NKD activity visible in the
log at that hour is the *legacy* night route on a different entry point. Track 1's NKD sleeve
has no evidence today and cannot get any until tomorrow's window.

**Swing** is configured with provider `none` unless an operator exports
`RAITS_TRACK1_SWING_PROVIDER`. Those slots will refuse by name rather than touch the broker —
by design, from Stage 5M-B.

---

## 4. Why Calm crashed and Stress did not

This is the part the brief had backwards, so here is the whole chain.

Both sleeves call the same function. Inside it, two checks run **in this order**:

```
track1_live_source.py:474    _refuse_overlap_disagreement(...)   ← raises LiveSourceRefused
track1_live_source.py:475    guard.splice(frozen, aligned)       ← raises SpliceRefused
```

The slot's error handling catches `ShadowRefused`, `FreshnessRefused`, `LiveSourceRefused` and
`NotImplementedError`. **`SpliceRefused` is in none of them** — it subclasses `RuntimeError`
and nothing else. So the *first* refusal becomes a tidy ledger row and the *second* kills the
process. Same severity, different class, opposite outcome.

Now the instruments. Calm reads **MES and MNQ**, sorted, so **MES goes first**. Stress reads
**MNQ only**.

I read both history files:

| | last stored bar | agrees with the live feed? | so it reaches… |
|---|---|---|---|
| **MES** (`ES_continuous_1m_8y.parquet`) | 2026-08-21 **13:44** | yes | the splice → **crash** |
| **MNQ** (`NQ_continuous_1m_8y.parquet`) | 2026-08-21 **13:45** | **no** | the overlap check → **caught, row written** |

The MNQ disagreement is one bar and it is a partial. History has the 13:45 low at
**29400.25**; the completed bar's low is **29395.75**. A snapshot taken mid-minute always
records a low that is too *high*, because the price had not yet fallen the rest of the way —
the sign is exactly right. Both files were last written 2026-08-21 at 13:45–13:46, which is
the daily append boundary the config file itself already warns about.

MES stops one minute earlier, at a bar that had finished. It has nothing to disagree about, so
it sails through to the splice and dies there.

**So:** the column mismatch is not a Calm problem. It is waiting for every instrument on every
sleeve. Stress is being shielded from it by a stale data file — and the moment that file is
refreshed, the shield goes away and twenty-four slots a day stop leaving any trace.

---

## 5. The answers to the five questions

**Does the column mismatch happen outside Calm 10:00?**
Not observed elsewhere today, but it is **universal, not Calm-specific**. History frames are
forced to exactly five columns for every instrument; the broker's fetch never trims, so it
always hands back IBKR's extra `average` and `barcount`. Any instrument that reaches the
splice mismatches. Stress is only spared because MNQ is stopped one line earlier.

**Does the uncaught refusal make a slot silent?**
**Yes — confirmed live.** The 10:00 slot left a `window_open` line and nothing else: no
`slot_observed`, no `window_closed`, no timing, no explanation. The audit could only report
"nobody looked", where a named row would have said what actually went wrong.

**Did the audit jobs run?**
**Yes.** Five registered at start-up. The Calm one fired at 10:10, finished in a second, wrote
its row. The rest are simply not due yet — except NKD's 03:05, which was already in the past.

**Did the audit write the right verdict?**
On what it could see, **yes** — "nobody looked" and "this slot id is missing" are both exactly
right. But its third reason, "no timing records", is **a permanent false FAIL**. See below.

**Any order attempt?**
**None.** No order text anywhere in the log, no arming file, no approval variable, and the
audit's own order-gate section records no order marks.

**Any write to the book or the checkpoint?**
**None.** Both files are absent and the API confirms it.

**Why did Track 1's max-hold job take one second?**
**Because there is no positions file — nothing else happened.** The job checks for the file
and returns immediately, *before* it takes the PID lock and *before* it would connect. The
proof is the legacy twin firing in the same second and taking ten: it has a file, so it
connected. One second versus ten is the difference between returning at the door and going in.

---

## 6. Two blockers nobody had written down

### The audit cannot pass, ever — regardless of the market

The Track 1 entry point contains **zero** references to the telemetry module. The legacy entry
point has sixteen. So the environment variable that turns telemetry on is set correctly by the
launcher, inherited correctly by the child, and read by nobody. The scheduler parent only
records telemetry when it *skips* a slot, never when one completes.

Two separate rules in the acceptance code turn that into a hard FAIL:

- a sleeve with no timing rows at all → **FAIL**
- every slot that wrote a ledger row but no timing row → **FAIL**

Which means fixing the crash and the column mismatch still leaves every audit red. A perfect
window would be graded FAIL.

**A prediction, so this claim can be checked rather than believed:** the **12:40** Stress audit
will come back **FAIL**, naming at least "slots could not evaluate" *and* "no timing records",
whatever the market did between 10:35 and 12:30. If it comes back any other way, I am wrong
about this.

### The history file is stale, and the staleness is load-bearing

The MNQ file's last bar is a partial written at the daily append boundary three sessions ago.
It is refusing every Stress slot today. It is a **data** defect, not a code defect, and it is
the thing currently standing between the Stress sleeve and the crash.

---

## 7. What I would do, and in what order

**Do not start Stage 5Q-3 yet.** That stage is about explanation evidence, and **no slot on
any sleeve reached the explanation writer today**. Any change there would be shipped
unexercised by the live route — which is the situation 5Q-1 and 5Q-2 were both written to get
out of.

1. **Catch the splice refusal.** One `except` clause. It turns today's silent crash into a
   named row, and it is the precondition for everything below.
2. **Trim the live fetch to the five columns.** Worth saying that the provider protocol's own
   docstring *already declares* it returns those five columns — the IBKR implementation
   violates a contract that is written down. This is enforcing an existing decision, not
   inventing a new one, so it does not need a design conversation.
3. **Wire telemetry into the Track 1 entry point,** or the audit stays red forever.
4. **Refresh the MNQ history file — strictly after step 1.** Doing it before step 1 silences
   the Stress sleeve.

Steps 1 and 4 are ordered by consequence, not preference. Getting them the wrong way round
costs a day of Stress evidence and does it quietly.

**Operator action needed right now: none.** Nothing is unsafe, nothing can place an order, no
state file is being written, and every remaining Stress slot today will keep leaving an honest
refusal row. This is a code decision, not an ops one — so no command is offered here, because
none is needed and an unnecessary restart would only cost the coverage collected so far.

---

## What I did not establish

- **Whether MNQ would also hit the column mismatch.** It has never reached the splice, so this
  is read from the code path rather than observed. The reasoning is solid — the trimming
  happens per instrument with no exceptions — but it is one step short of measured, and it
  becomes measured the moment step 4 above happens.
- **What the Stress sleeve would have decided** on a clean feed. Nothing today got as far as
  the gate, so today says nothing about the strategy — only about the plumbing.
- **The swing and NKD sleeves' live behaviour.** Neither has run under this scheduler.
