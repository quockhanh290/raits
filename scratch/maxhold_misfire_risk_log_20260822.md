# Risk log — 2026-08-04 max-hold exit incident

**Class: trading-job incident.** Not scheduler maintenance. Filed separately on purpose — the first
version of the timing report grouped it with 51 overnight-maintenance misfires and that description
hid it.

Read-only reconstruction. No service was started, no order was sent, nothing was committed.

---

## Correction to my own earlier statement, first

Both the timing addendum and the Stage 0 readiness report said the job **"fired 41 minutes late"** /
"missed by 2,476 s". That describes the *warning line*, not what happened.

**The job did not run at all.**

`SLOT_MISFIRE_GRACE_SECS = 300` (`run_scheduler.py:363`). The delay was **2,475 s — 8× the grace** —
so APScheduler dropped the run rather than executing it late. Verified in the logs: on 2026-08-04
there is a `Run time of job "MAX_HOLD exit 09:31 ET" … was missed by 0:41:15` line and **no
`Running job` line and no `executed successfully` line**. A normal day (2026-08-21) shows both, 10
seconds apart.

"Late by 41 minutes" and "did not happen" call for different responses. The corrected statement is
the second one.

---

## What happened, in sequence

| when (machine local, MDT) | what |
|---|---|
| 2026-08-04 00:56:28 | `scheduler_0803.log` — NKD night 02:55 completes normally. Last healthy line. |
| — | **Machine enters S3 sleep.** Confirmed against the OS: Power-Troubleshooter records a suspend covering this window. |
| 2026-08-04 08:12:15 | Wakes. APScheduler reports `MAX_HOLD exit 09:31 ET` missed by 2,475 s. Past the 300 s grace → **run dropped**. This is the final line of `scheduler_0803.log`; that process ends here. |
| 2026-08-04 08:44:55 | A **new** scheduler starts → `scheduler_0804.log`. |
| — | No catch-up runs. **`_catch_up_maxhold` did not exist yet** — see below. |
| that day | Pre-flight also failed: **26 pre-flight skips**, all 23 day-window slots skipped. `run_live_day` never ran, so the 14:05 retry path that normally rescues a pending exit never ran either. |

**2026-08-04 was broken in more than one place.** The max-hold exit never ran, and neither did any
day-window slot.

---

## Status: already fixed for the observed sequence

`_catch_up_maxhold` (`run_scheduler.py:1132`) was added on **2026-08-07**, three days after this
incident, in commit `91dbc0e` — *"fix(scheduler): run the missed 09:31 MAX_HOLD exit at startup"*.

It runs today's 09:31 close if the scheduler comes up after 09:31 ET and the day is not already
marked done. Its own docstring names exactly this failure: *"APScheduler schedules the NEXT
occurrence at startup, so a scheduler started at 09:43 does not have a late 09:31 job — it has no
09:31 job at all. Nothing misfires, nothing is logged."*

Applied to the 2026-08-04 sequence, the restart at 08:44 local (10:44 ET) **would** have triggered
it. So the observed path is closed.

### Evidence that it has held since

| | measured |
|---|---|
| `MAX_HOLD exit 09:31` misfires since the fix | **0** |
| Sleeps spanning 09:31 ET on a weekday, since the fix | **0** (six exist in the 40-day power window; the most recent is 2026-08-05, before the fix) |
| Days since 2026-08-09 with a normal `Running` + `executed successfully` pair | every one, apart from days where the catch-up path logged instead |

---

## Residual hole — not observed, not structurally closed

The catch-up is **startup-only** (called once in `make_scheduler`, `run_scheduler.py:1243`). A
scheduler that is **already running**, sleeps through 09:31, and is **never restarted** gets:

- no cron run — the misfire is past the 300 s grace, so APScheduler drops it, and
- no catch-up — nothing restarted.

The process survives S3 suspend, so this is reachable whenever the operator wakes the machine
without restarting the scheduler. It has not happened since 2026-08-07 in this sample, but nothing in
the design prevents it.

**Suggested follow-up (not implemented here):** the catch-up predicate is already the right one —
"it is past 09:31 ET, today is a weekday, and `_maxhold_done[today]` is unset". Evaluating it on the
heartbeat as well as at startup would close the hole without a new job, a new argv, or a change to
any trigger. That belongs with the Track 1 scheduler work, not in this pass.

---

## What could NOT be reconstructed, and what would be needed

The task asks for position affected, intended vs available exit price, and P&L impact. **None of
that is recoverable from what is on disk today**, and saying so is the honest answer:

| wanted | why it is not available |
|---|---|
| Which position(s) were at `hold >= 5` on 2026-08-04 | `live_positions.json` (481 B) holds only current state, last written 2026-08-21. There is no dated position snapshot. |
| Intended exit price (09:31 ET RTH open) | no trade-log row exists for 2026-08-04; `paper_history.json` is 359 B and current-only |
| Price actually available when it did close | unknown — no evidence the position closed that day at all; the 14:05 path was also skipped |
| P&L impact | not computable without the two prices above |

`live_day_0803.log` and `live_day_0804.log` contain **no** `MAX_HOLD_EXIT` lines and no `held=N days`
lines, so even the question *"was any position actually due?"* cannot be answered from them.

### To answer it, one of these is needed

1. **A dated position snapshot.** `live_positions.json` is rewritten in place. A daily copy —
   or the existing atomic write extended to keep the previous version — would make any future
   incident reconstructible. Cheapest and highest value.
2. **Trade-log rows retained per day.** `_append_trade` writes CLOSE rows with `expected_stop`,
   `fill_price`, `exit_reason` and `hold_days`; if those rows are retained and dated, the intended
   and actual prices are both there.
3. **Reconstruct from the broker.** IBKR execution history for 2026-08-04 would settle whether
   anything closed and at what price — **explicitly out of scope here** (no IBKR connection), and it
   would need an operator to pull it.

Until one of those exists, the correct entry in this log is: *the 09:31 close did not run on
2026-08-04; whether a position was due, and what it cost, is unknown and currently unknowable.*

---

## Bearing on Track 1

Small, and it is not a runtime matter:

- It is **not** evidence against the Track 1 slot plan — no day-window slot was involved.
- It **is** evidence for gate G3 (see the collection runbook): the incident was caused by an OS
  suspend, and suspends are still happening on essentially every trading day.
- It is a reminder that the same suspend inside 10:35–12:30 would hit the Stress detector, which —
  unlike the swing sleeves — has **no idempotent next slot to fall back on** for its 15:55 exit.

## Provenance

| item | source |
|---|---|
| grace constant | `global_index/run_scheduler.py:363` |
| missing Running/executed pair | `scheduler_0803.log`, `scheduler_0804.log` |
| catch-up implementation and call site | `global_index/run_scheduler.py:1132`, `:1243` |
| fix date and commit | `git log -S"_catch_up_maxhold"` → `91dbc0e`, 2026-08-07 |
| OS suspend confirmation | Windows `Microsoft-Windows-Power-Troubleshooter` event log, read-only |
