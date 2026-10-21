# Batch 1 correction — what the risk wiring still does not say

Read this whole file before touching anything. It has two parts and they have different rules.
Part A is two small fixes. Part B is a report with NO code changes at all.

Batch 1 is accepted. Its own suite is 10 of 10 green and I re-ran it myself. The kill switch does
stop the send, the reconcile halt does reach new entries only, and both reader flaws are closed.
This file is about three things Batch 1 left behind, two of which I can describe exactly.

Do not re-open anything Batch 1 closed.

---

## Part A — two fixes

### A1. The reason is computed and thrown away

In the live slot, the step that seeds the circuit breaker from the route book returns a small
dictionary saying whether the breaker came out armed, from which file, and when unarmed, why. The
call site assigns it to a local name and never reads it again.

The consequence: the slot runs with no circuit breaker at all, and the durable row written for
that slot says nothing about it. Someone reading that row a week later cannot tell a slot that ran
under a working drawdown limit from a slot that ran with none.

What to do: carry that state into the durable slot row the same way the count of already-held
positions was carried there — as fields on the row, not as a log line. The scheduler drops a clean
slot's standard output by level, so a number printed there cannot be checked afterwards. That is
why held-at-decision went into the row and not into a print, and the same reasoning applies here.

At minimum the row must be able to answer two questions without reading any other file: was a
breaker in force for this slot, and if not, what was the stated reason.

Do not invent an equity number to make the breaker look armed. Part B is about why there is no
number to use. Unarmed-and-said-so is the correct outcome today.

### A2. The kill-switch gate pins the helper, not the wiring

The existing gate asserts what the summary function returns when the stop file is present. It
never asserts that the slot skips the send.

Delete the single line that makes the send conditional on that summary and all ten Batch 1 tests
stay green. I checked: neither Batch 1 suite nor the older kill-switch suite mentions the slot
function at all.

We have a standing rule about exactly this shape, written after a safety mechanism turned out to
have code, a runbook and a passing grep, and no call site. The wiring here is genuinely present.
It is simply unpinned.

What to do: add a gate that fails when the send becomes unconditional. Assert against the call
site, not the helper. A gate that passes when the wiring is removed is not a gate.

### Gates for Part A

Every one of these must be shown as measured output in your report, not asserted in prose.

- G1. The new row fields appear in a real slot row, in both states: once with a breaker in force,
  once unarmed with the reason. Show both rows.
- G2. Falsifiability, stated per new test: describe the one-line mutation each new test catches,
  and show it going red under that mutation before you show it green. A test that cannot be made
  to fail has measured nothing.
- G3. The new kill-switch gate goes red when the send is made unconditional. Show the red run.
- G4. No regression. REWRITTEN 2026-09-26 — the earlier version of this gate was wrong and you were
  right to stop on it. Read this whole item; the old instruction to reproduce a 203-test failing set
  is withdrawn.

  What went wrong with it. I froze the failing set of the full list, scratch included, and made
  reproducing it a condition. Your run came back with 201 and the two missing ones were tests that
  had gone GREEN, not red. I chased both:

  One reads the live scheduler process and skips when the process query comes back empty. The
  scheduler never stopped — same process, still running, and it does carry the arming flag, so the
  test fails whenever it can actually see the argv. Under a thirty-seven-minute fully loaded run the
  query returned nothing and it skipped instead, which matches the extra skip in your totals. A
  test that quietly skips under load cannot be a member of a frozen baseline.

  The other is a browser test that passes when run by itself and failed inside my forty-two-minute
  run. Same tree, different load. Not proven to the mechanism, but the signature is load, not code.

  So the fault was mine: I built a gate on a basis that is not a function of the tree. A frozen set
  is only meaningful over tests whose verdict depends on the code, and most of that scratch
  directory depends on live process and filesystem state instead.

  The gate now, in two parts:

  BLOCKING. Only the production suites from that list — every test file under global_index and
  monitor that imports either changed module. Ten files. Measured by me on 2026-09-26 after the
  operator applied an unrelated book repair and I updated the one golden it legitimately moved:

      1 failed, 133 passed, in 30 seconds

  That single failure is the weekday-prefix string in the dashboard truthfulness suite, and it
  belongs to the other batch, not yours. Your after-run must be exactly this: the same one failure
  and nothing else. Thirty seconds, deterministic, and it is where a real regression in your change
  would actually appear.

  INFORMATIONAL, not blocking. The scratch portion. Run it if you want the wider picture and report
  what you see, but a difference there is a note, not a stop. Two members are known to flap with
  load, and the rest assert that this route cannot trade — no confirmation file, no orders
  directory, a flat book, an unimported executor, a long blocker list — all of which read live
  state and all of which are false on purpose now that the route is armed. The earlier baseline
  files remain at the repo root for reference only; they are no longer a gate.

  Do not fix, skip or rewrite anything in the scratch directory.

  If any production suite fixture encodes the old silence — that is, asserts that the row says
  nothing about the breaker — say which and stop. You do not have permission to rewrite a fixture
  in this batch.
- G5. Over-application. Show that a slot whose breaker IS armed is unaffected: same decisions,
  same verdicts, same counts as before the change. The new fields are additive.

---

## Part B — report only, change no code

### B1. The four-percent daily-loss arm cannot fire on this route

Two independent reasons, and I want you to confirm or refute each with your own measurement rather
than agreeing with mine.

Reason one, the re-base. Every slot is its own process, so the book always opens with no current
day, and opening the instant re-bases the day starting equity to the equity as it stands right
then. I measured it: a book seeded with a start of 54,000 and an equity of 51,000 — a 5.6 percent
day, past the four percent limit — reports a daily loss of exactly 0.00 percent, because the
starting figure was overwritten with 51,000 at the moment the instant opened. I swept five
equities from 52,000 down to 41,000 against a peak of 55,000 and the daily figure was 0.00 in all
five.

The peak-drawdown arm does work. Same sweep: warn and half size at about 11 percent, refuse at
about 15 percent.

Reason two, and the one that matters more: nothing writes an equity mark to this route book. The
three fields are zero in the live file, the book repair writes them as zero on purpose and says in
its own output that they are reconstructed rather than recovered. So even with the re-base fixed
there is no number to base a day on.

Note that the book DOES carry which session day it belongs to. That is the only piece of the
puzzle that is present.

What I want in the report:

- Whether each of the two reasons holds, measured, with the commands and output.
- Every component that could mark equity on this route, what it would have to read, and at what
  instant it would have to write. If the honest answer is that no such component exists yet, say
  so plainly — that is a build decision for the operator, not a fix for you to make.
- What the record should say in the meantime. As long as the daily arm is unreachable, an armed
  breaker on this route means one thing only: a peak drawdown limit. Anything in the record or on
  the dashboard that calls it a circuit breaker is overstating it. Tell me where those words
  appear.

Do not implement a fix for B1. Do not seed the day from the book, do not add a writer, do not
change any threshold. Report, and stop.

---

## Scope

The live slot, the signal layer, and the tests for them. Do NOT touch any dashboard or monitor file
— a separate batch is running on those at the same time and the two must not collide. If a fix here
seems to require one, stop and say so; that is a finding, not a blocker to route around.

No broker orders. No book writes. No scheduler or backend restart. No commits.

---

## How to answer

One report, two sections matching the two parts. For Part A, the five gates with their measured
output including the two red runs. For Part B, findings only.

Three labels, and keep them apart: verified by my own measurement · claimed but not measured ·
cannot tell from here. Do not collapse the third into the second. If a gate cannot be measured,
say which and why, rather than reporting it as passed.

Wait for my review of the Part B findings before any code is written for them.
