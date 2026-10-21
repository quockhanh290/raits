# READ-ONLY REVIEW: is each risk layer actually ARMED on the Track 1 route

**Change no file.** Not source, not tests, not notes. This ends with a report.

ENGLISH only. No git add or commit. No scheduler or backend restart. Do not place or cancel any
broker order. Do not run the whole test suite — 80 minutes, 282 unrelated failures under separate
triage.

---

## 0. The question, stated precisely

Not "does this repository contain a circuit breaker". It does. The question is whether each risk
layer is **wired into the path the Track 1 route actually runs**, and whether the input it reads is
a real measurement rather than a default.

This repository has a recorded history of exactly that gap: a safety mechanism with code, tests, a
runbook and a grep-verified comment, connected to no entry point. Treat every "it exists" as
unanswered until you have followed it from the live entry point to the branch that enforces it.

Two failure shapes to hunt, both seen here this week:

  * **not wired** — the check exists and nothing on the live path calls it
  * **wired to a constant** — the check runs, on an input that never changes, so it cannot fire

The second is more dangerous. It produces a green light, a passing test, and a log line saying the
check ran.

---

## 1. Start here. One finding, already measured, to prove or refute.

**The circuit breaker may be reading a number that resets every five minutes.**

What was measured, 2026-09-25 19:5x ET:

    the live slot builds its book as
        Track1Book(guard=make_guard(), breaker=CircuitBreaker(account=ACCOUNT), enforce_windows=True)

    Track1Book's equity field defaults to ACCOUNT, which is 50000.0
    the route's book file carries   equity 0.0   peak_equity 0.0   day_start_equity 0.0
    the breaker is driven from the book's equity, in begin_instant:
        start_day(self.equity) on a day roll, then update(self.equity), then
        status(self.equity) decides allow_new_entries

Every slot is a separate process and builds a new book. Nothing in the live slot path restores
equity, peak_equity or day_start_equity from the file — the restore that does exist belongs to the
replay bootstrap, which the live slot does not use.

So the hypothesis: on this route the breaker starts each slot at the account base, sees no change
within the slot, and cannot trip on drawdown at all.

Prove it or refute it. If it is true, say what WOULD have to be true for it to fire, and whether any
path on this route makes that true. If it is false, say exactly which line restores the state and
show the value it restores.

Note the second half, which matters even if the first is refuted: the three carried fields on disk
are all 0.0 after two days of real fills. Whatever is supposed to write them is not writing them.

---

## 2. The other layers. For each: wired, wired-to-a-constant, or absent.

For every one, give the entry point, the call site, the branch that enforces it, and one measured
example of it being evaluated on this route.

**2.1 Kill switch.** A STOP_TRADING file for this route. Which paths check it? Does the check sit
before or after the decision to send? What happens to a slot mid-run if the file appears?

**2.2 B3 halt on broker/book mismatch.** The runner sets a halt flag when the broker and the file
disagree. Does that flag reach the Track 1 entry path, or only the legacy loop? This route hit a
real mismatch on 2026-09-25 — the book was empty while the broker held three positions — and entries
were not halted on the Track 1 side. Establish whether that is because the flag does not reach it.

**2.3 Cluster and family caps.** These read the book's open positions. Until 2026-09-25 the live
slot built that list empty, so the caps saw zero exposure; that is now seeded. Confirm the caps are
evaluated against the seeded list, and report what they currently compute for each cluster against
its limit. Four positions are open as you read this.

**2.4 Position sizing.** Where does risk per trade come from, and is it computed against a real
equity figure or against the account constant? The same question as section 1, one layer down.

**2.5 Freshness gate.** The route refuses to decide on stale inputs. Confirm it can refuse — find a
measured instance in the evidence, not just the code.

**2.6 The order gate.** Two factors are required: the blocker registry and an out-of-band approval.
Confirm both are read at the moment of sending, not at process start, and that an overridden blocker
still reports itself as overridden rather than as released.

**2.7 Stop placement and the naked-position check.** Which job places a deferred stop, and what
audits that every open position has one? Note that a separate task is already open on the arming
rule's input; do not duplicate it, and do not modify global_index/runner.py.

**2.8 Max hold.** Which job closes a position that has run its maximum duration, and what happens if
that job fails or is skipped?

---

## 3. The three-state question, applied to every layer

For each layer, answer: when the check **cannot be evaluated** — the file is unreadable, the broker
does not answer, the record is stale — does it fail closed, fail open, or answer as if it had
measured something?

This is where the week's worst defect lived: a book that could not be parsed was answered as a book
holding nothing, and three live positions lost their record and their stops while two jobs reported
success. Look for the same shape everywhere.

---

## 4. What is in scope

    global_index/track1_signal_layer.py      the decision layer and its book
    global_index/run_live_day_track1.py      the live slot entry point
    global_index/track1_gates.py             the blocker registry
    global_index/track1_paper_send.py        the send wire
    global_index/track1_paper_executor.py    the order layer
    raits/risk/                              breaker, sizing, guards
    the evidence on disk: live_positions.track1.json, the order journal, the trade log,
                          window_coverage, and the scheduler log

READ ONLY, all of it. Do not modify global_index/runner.py or the two sweep entry points — they are
under a separate open task. Do not report findings in global_index/dash/realtime/realtime.js,
monitor/backend/track1_market_view.py or monitor/backend/job_journal_reader.py; another session is
editing those right now.

---

## 5. Report

    SECTION 1        proved or refuted, with the lines and the values
    LAYER TABLE      one row per layer from section 2: WIRED / WIRED-TO-CONSTANT / ABSENT, the
                     enforcing branch, and the measured example
    THREE STATES     one row per layer: what it does when it cannot measure
    FINDINGS         ordered by what could cost money, not by what is easy to fix. For each: what
                     is claimed, what is true, and how you know
    NOT A DEFECT     mechanisms that look unarmed and are deliberately not armed, with the reason.
                     Several on this route are deliberate — a deferred stop is not a missing stop
    UNCHECKED        what you did not reach, and what it would take
    SPEC PROBLEMS    anything here you believe is wrong, or empty — and if empty, say you looked
