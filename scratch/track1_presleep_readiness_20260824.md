# Pre-sleep hardening for the Track 1 overnight shadow

**2026-08-24 ·** scheduler **not** restarted or stopped (pid 33868, started 02:32:24 local =
04:32 ET, unchanged before and after) · backend **not** restarted — the restart it needs is
*reported*, not performed · no IBKR connection · no order · no `STOP_TRADING`,
`STOP_TRADING.track1` or confirmation file created · `TRACK1_ORDERS_APPROVED` unset ·
`--allow-orders` nowhere · no commit.

**No order enabling was done. Nothing in this work moves the route closer to trading.**

---

## Verdict right now: **`WARNING_ONLY`**

**The overnight NKD window will be captured. One thing about the screen is wrong, and it
needs one command.**

```
[OK  ] 1  single scheduler        pid 33868, started 02:32:24 local, up 8471s
[OK  ] 2  track1-only flag        argv carries --track1-only-shadow
[OK  ] 3  backend slot table      state_slot_count=70 (1 Calm + 24 Stress + 23 Swing + 22 NKD)
[OK  ] 4  track1-runtime endpoint route=track1_candidate, coverage present, timing present
[OK  ] 5  window_coverage dir     exists, empty (nothing has run yet)
[OK  ] 6  slot_timing dir         exists, empty (nothing has run yet)
[OK  ] 7  broker feed             connected=True freshness=fresh age=0.6s
[OK  ] 8  orders impossible       B1 open, orders_possible=False, no confirmation file, env unset
[OK  ] 9  no duplicates           one scheduler, one backend, one listener on 5002
[OK  ] 10 next window             Calm 10:00 ET in 3.1h; overnight NKD 01:10-02:55 ET in 18.3h
[WARN] 11 pre-start NKD slots     code on disk: correct.  RUNNING BACKEND: still says late.
```

### The one operator action before sleep

```powershell
python monitor/ops.py restart --backend
```

**Do not restart the scheduler.** It is correct and it is the thing holding the night.

---

## The false alarm, and what it actually was

The operator started the track1-only session at **04:32 ET**. The NKD window runs
**01:10–02:55 ET**. The whole window had already passed — by two and a half hours — before
the process existed.

Measured against the running dashboard:

```
freshness: late
unexplained_overdue: 22
    TRACK1_NKD_0110 not_observed unknown watch 2026-08-24T05:10:00Z
    ... 21 more
```

Twenty-two slots reported late, over a route that had not yet been asked to do anything.

Every one of those slots was "unobserved" for the only reason a slot can be unobserved
without anything being wrong: **there was no process to observe it.** The acceptance gate
already reasons exactly this way — a window that closed before the scheduler existed is
`NOT_ENOUGH_DATA_YET`, never a failure. **The dashboard was disagreeing with the gate**, and
that disagreement is how an operator wakes to a red "pipeline late" banner over nothing, and
learns to stop reading the banner.

### The fix

A slot with **no evidence at all**, belonging to Track 1, whose instant is **strictly
before** the scheduler's start, is now classified:

```
state:    not_applicable
reason:   before_scheduler_start
severity: none
detail:   slot instant … is before the scheduler started at … ; no process existed to run it
```

It is **classified, not dropped**. Vanishing quietly from the overdue list would be
indistinguishable from the slot having run — the operator needs to be able to read why.

Measured, same tree, same moment: **22 → 0 overdue**, `freshness` goes from `late` to
`not_expected_yet`, which is the true answer at 06:53 ET with no window open.

### Three limits, so it cannot hide a real miss

| Limit | What it stops |
|---|---|
| **No evidence at all** | A slot with a log line is explained by that line. A marker with no verdict in it — something started and never finished — stays on the alarm side, because the line itself disproves "no process existed" |
| **Strictly before, not before-or-equal** | A slot due at the very instant the process came up *had* a process. The boundary belongs on the alarm side |
| **Track 1 ids only** | The same reasoning applies to a legacy slot, but legacy has its own restart handling and a long-tuned alarm surface. Widening it here would risk masking a legacy alarm in order to fix a Track 1 one |

**A slot after the scheduler start with no evidence past its allowance is still late** —
pinned by a test that moves the start to 00:30, before the window opens, and requires all 22
to go back to overdue with `freshness: late`.

### One more thing that had to not break

The rule needed the start instant, which `_evidence()` had no access to. A start time that
cannot be read now yields `None`, and every caller treats `None` as *do not apply the rule*.
That is the safe direction: it can only ever leave a slot reported as it was, never suppress
one. Both cases — nothing running, and an unparseable timestamp — are tested and leave all 22
overdue.

---

## Why the screen is still wrong

| | |
|---|---|
| backend pid 3468 started | **03:26:41 local** |
| the classification fix landed | **04:50:53 local** — 1h24m later |

**The running backend predates the fix and serves the classifier it was started with.** I
queried it after the change and it still returns 22 — **I did not fake the corrected result.**
One of the tests exists purely to keep this honest: it prints what the live endpoint actually
says, so the suite can never be read as proof that the *live* dashboard is fixed. Only a
restart does that.

**The night's evidence is unaffected.** The scheduler writes the window ledger and slot
timing; the backend only reads them. A stale backend means the morning screen lies about the
past, not that the night went unrecorded.

That is precisely why the verdict is `WARNING_ONLY` and not `NOT_READY`. The two failures are
different and must not share a light:

```
NOT_READY      the window will not be captured, or an order could be sent
WARNING_ONLY   the window WILL be captured; the screen will lie about it
```

Collapsing a stale dashboard and a dead scheduler into one red light is the same mistake as
an alarm that never clears.

---

## The pre-sleep script

`scratch/track1_presleep_readiness_20260824.py` — read-only, eleven checks, three verdicts,
writes only its own JSON summary beside itself.

```powershell
python scratch\track1_presleep_readiness_20260824.py
```

Two design points worth naming:

**The process table gets three outcomes, not two.** "Could not read the process table" is
reported as *unknown*, never as *one is running*. That exact fail-open shape is what let a
second scheduler start once before, and two schedulers contending for one client id is what
cost six entry slots.

**The countdown obeys the trading calendar.** "In 3h" across a holiday is a wrong number, not
a rounding error — and it is the number someone would set an alarm by. It also names the
**overnight NKD** window explicitly, not just the nearest one: the nearest window is Calm at
10:00, but the window the operator is asleep for is NKD, and answering only the first would
answer a question nobody asked before bed.

Its own summary, written this run:

```
next window roska4_calm 10:00 ET in 3.11h   (Mon 2026-08-24 10:00 ET)
overnight   global_nkd  01:10-02:55 ET in 18.27h (Tue 2026-08-25 01:10 ET)
```

---

## Tests

| | Result |
|---|---|
| `test_track1_presleep_schedule_status_20260824.py` (new, 13) | **13 passed** |
| `test_track1_presleep_readiness_20260824.py` (new, 24) | **24 passed** |
| Mutation check on the classifier | **6 / 6 detected**, `schedule_status.py` restored byte-for-byte |
| Mutation check on the readiness script | **13 / 13 detected**, restored byte-for-byte |
| `monitor/` production suites: schedule-status Track 1 + dashboard backend + realtime contract + ops | **259 passed** |
| Track 1 scratch sweep: pre-sleep ×2 + dashboard wiring + ops status + 5P ×2 + 5O + 5N + 5M-D | **231 passed** |

`global_index/test_event_playback.py` **not run** — known hang.

### A defect in my own test, caught by the mutation harness

The check "evidence wins over the clock" passed, and it was **testing nothing**. I wrote it
with a log line reading `exited with code 1` — but that line returns from an earlier branch
and **can never reach the pre-start rule at all**. Deleting the guard I meant to be defending
left the test green.

The line that actually reaches the rule is an *unrecognised* one — a marker with no verdict
in it. Rewritten to use that, the mutation goes red. Same lesson as before: a test can assert
a true property through a path that never touches the code under test, and only a mutation
tells you which.

Eleven of the readiness script's thirteen mutations are of the form "remove one way it can
say no"; the other two remove the environment restore and the trading-calendar check. A
readiness check never observed failing is a banner, not a check.

---

## What is NOT claimed

- **Not** that the live dashboard is fixed. The code is; the running backend is not, until it
  is restarted.
- **Not** that Track 1 is paper- or live-ready. `B1_broker_account_or_legacy_retirement` is
  still open and `orders_possible` is still False, which is the intended state.
- **Not** that the NKD window will produce a passing shadow day. Nothing has run yet;
  `window_coverage` and `slot_timing` are both empty directories. The acceptance verdict
  stays `NOT_ENOUGH_DATA_YET` until a window closes with the scheduler up for all of it.
- **Not** measured: broker-flat, orphan working stops, or the legacy book's drain. This work
  did not connect to IBKR.

---

## In the morning

```powershell
python scratch\track1_shadow_audit_20260824.py        # did the NKD window pass?
python scratch\track1_presleep_readiness_20260824.py  # is the session still healthy?
```

The first NKD window fully covered by scheduler uptime is **Tue 2026-08-25, 01:10–02:55 ET**
— 22 slots, the first judgeable window of the shadow period.
