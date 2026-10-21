# PHASE 1 (READ-ONLY): investigate five dashboard defects and propose the fixes

**You are not fixing anything in this phase. Change no file.** Not source, not tests, not notes.
Phase 1 ends with a report. Phase 2 is a separate instruction you will only get after that report
has been reviewed and cross-checked, and it may tell you to do something different from what you
proposed.

If you find yourself about to edit a file, stop: that is phase 2.

Read this whole file before doing anything. Every item below was measured on the running system
during the night of 2026-09-25, and each carries the command to repeat the measurement.

All output you write -- your report, any scratch notes -- in ENGLISH only.

## Why the gate exists, so you can aim at the right target

The person reviewing your report will re-run your measurements himself. A report that says "fixed"
or "confirmed" without the command and its raw output cannot be checked and will be sent back. Two
things have gone wrong here recently and both are your job to avoid:

- A session reported four failing tests in one file; re-running found them in a different file and
  the original file passing 10/10. The count was right and the location was wrong, and someone spent
  a turn hunting tests that did not exist.
- A session published a cause ("a duplicate order reached the broker") taken from a printed counter
  instead of from the code. Reading the code showed the order never reached the broker: the counter
  incremented inside an exception branch.

So: **quote the command, quote the output, and name the file and line you read it from.** Where a
claim rests on reading code rather than running something, say which function and which line.

## What I most want from you in this phase

Not agreement. This specification was written by someone who had been awake for a long time, and at
least one item in it may be wrong. Disagreeing with it, with evidence, is the most valuable thing
you can return. For each item, answer in this order:

1. Does the defect reproduce? Paste the command and the output.
2. If it does not reproduce, say so and stop on that item. Do not invent a different defect to fill
   the slot.
3. If it does, what is the mechanism -- which function, which line, which branch?
4. What is the smallest change that fixes the mechanism, and what would it break if wrong?
5. What gate proves the fix, including the assertion that would catch it being applied too widely?

---

## 1. Files in scope

You may READ anything in the repository. In phase 2 the only files you would be allowed to change
are these -- so if your proposal needs a file outside this list, that is a finding to report, not a
reason to widen it yourself:

    global_index/dash/realtime/realtime.js
    monitor/backend/track1_market_view.py
    monitor/backend/job_journal_reader.py
    monitor/test_realtime_dom.py
    monitor/test_job_row_never_invents_a_cause.py
    scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py   ONE marker only -- see item 3
    plus any NEW test file you create under monitor/

Do NOT touch anything else. In particular, leave these alone:

    global_index/track1_signals.py          the signal row's vocabulary feeds gates; see item 4
    global_index/track1_signal_layer.py     the decision rules
    global_index/run_live_day_track1.py     the slot path
    global_index/track1_paper_send.py       the order layer
    global_index/track1_gates.py            the blocker registry
    monitor/ops.py
    TASK.md and SCRATCHPAD.md

Do NOT modify production trading code, do NOT run git add or git commit, do NOT delete any
.parquet file or anything under data/cache/.

**Timing, for phase 2 -- stated here so your proposal can account for it.** A trading slot is a fresh process every five minutes and it
imports from global_index/, so editing a file there mid-window hands a half-written module to a real
run -- that cost a live slot on 2026-09-25 at 02:05 ET (NameError from an edit in progress). None of
YOUR files are imported by a slot: realtime.js is served to a browser, and the two backend readers
are imported by the dashboard process, so phase 2 can be done at any hour. Reloading the backend
after a phase-2 change uses --no-scheduler so the live scheduler is never touched:

    python -m monitor.ops restart --backend --no-scheduler --yes

Do not run that command in phase 1. Nothing has changed yet.

---

## 2. The five items

### Item 1 -- "missed" means two different things, and one of them is wrong

Measured, 2026-09-25 02:2x ET, the NKD window. The Market View lists all 22 slots. Five of them
read status "missed" with the reason "no record was written for this slot":

    01:10  01:15  01:20    the slot RAN and exited code 2: the order gate was shut, stdout said
                           "REFUSED - order sending was requested and is not available" and
                           "Nothing was run."
    02:00                  the slot RAN and died: ConnectionRefusedError [WinError 1225] -- the IB
                           Gateway restart window, which opens at 00:00 machine time
    02:05                  the slot RAN and died: NameError from a source edit in progress

Every one of those has a launch line AND a failure line in monitor/logs/ops_scheduler.err.log, and
the job journal already holds a distinct reason for each. So the system knows three different
things and the panel shows one sentence that fits none of them.

"missed" properly means the scheduler never fired the slot. That is a fourth state and it must stay
distinguishable, because the operator action differs: a slot that never fired is a scheduler
problem, a slot that fired and was refused by a gate is an evidence problem, and a slot that fired
and hit WinError 1225 is a Gateway problem that will clear by itself.

The direction a fix would take, for you to confirm or reject: give track1_market_view.py a state for "fired and produced no decision record", carry
the slot's own reason from the job journal into it, and let the panel show that reason. Keep
"missed" for slots with no launch line at all.

Repeat the measurement:

    curl -s http://127.0.0.1:5002/api/v1/track1-market-view

then read market_view.sleeves.global_nkd.slots and compare each slot_id against
monitor/logs/ops_scheduler.err.log for the same date prefix.

### Item 2 -- the journal reader throws away the only line that says why

monitor/backend/job_journal_reader.py, in the loop that walks scheduler log lines:

    if detail.startswith(("stdout:", "stderr:")):
        if current is not None and detail.startswith("stderr:"):
            ... append to diagnostics
        continue

Only stderr becomes a diagnostic. The gate refusal prints on **stdout**. So diagnostics comes back
empty and the impact falls through to the catch-all "The job emitted an unclassified error", while
the child had said in plain words what happened.

The comment beside that branch is correct about why stdout must not be read as a LAUNCH line -- a
traceback frame quotes the interpreter path, and an older version counted every such frame as a new
run. That reasoning does not extend to diagnostics, and this is the right fix to make: keep stdout
out of launch detection, let it into diagnostics.

Watch the volume. _MAX_CHILD_DIAGNOSTICS already caps the list, and the gate is that a CLEAN run
must not gain diagnostic lines it did not have before -- see section 3.

This item is the upstream cause of item 1 and of a defect already fixed in realtime.js, so do it
before item 1 and item 1 gets easier.

### Item 3 -- no issue row says whose problem it is

issueScope() in realtime.js maps a scope to a chip label: TRACK 1, LEGACY, BOTH ROUTES, MODEL. It
appears exactly once in the whole file -- its own definition. **Nothing calls it.**

Stage 5ZZZ-CM removed the four issue-group headings and justified it in a comment saying each item's
scope stays on its own row's chip. That chip does not exist. Measured in the DOM with the suite's
own four-issue payload:

    SCHEDULER | OPEN       | Track 1 slot table stale        route_scope: track1
    SCHEDULER | OPEN       | SESSION_REPORT MISSED           route_scope: scheduler
    RUNNER    | KNOWN DEBT | Model age remains HARD stale    route_scope: known_debt
    PAPER     | OPEN       | Paper vs Flex P&L mismatch      route_scope: legacy

The first two rows are indistinguishable -- both read SCHEDULER -- and one is Track 1's own while
the other serves both routes. None of the four labels appears anywhere in the panel. That is exactly
the confusion Stage 5ZZH was built to remove: "five issues sat in one flat list beside the Track 1
panel, four of them about a route that is not this one".

There is already a test recording this, left deliberately failing:

    scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py
      test_dom_every_row_says_whose_problem_it_is     xfail(strict=True)

A fix would wire the chip into the row. Note the consequence for your proposal: when the chip
renders, that xfail(strict=True) flips to XPASS and the suite FAILS on the unexpected pass, so the
marker has to come out in the same change. Name that in your plan. In phase 2 the only thing you
would change in that file is the marker.

### Item 4 -- a slot that placed a real order is labelled "shadow only"

The 01:25 ET slot sent an order to the paper broker and it FILLED: MNKD LONG x1 at 66,145, order id
40, four rows in the order journal ending in filled. The Market View's reason for that slot reads
shadow_only, and the job row reads ACCEPTED SHADOW.

The field is not lying in its own terms: it comes from status == SIGNAL_ACCEPTED_SHADOW in
track1_signals.py and describes the DECISION layer. It became misleading when the route started
sending, because to a reader "shadow only" means nothing was sent.

**Do not change track1_signals.py.** Its vocabulary is read by gates and an evidence row that
changes meaning is a bigger problem than the label. Instead, join what is already on disk: the order
journal names the sent order ids and the filled trade ids per day, and track1_report
already reads it:

    python -c "from global_index import track1_report as R; import json; print(json.dumps(R.read_order_journal('.'), indent=1, default=str))"

Measured output for 2026-09-25: source "paper_send", sent_order_ids ['40'], filled_trades
['global_nkd::MNKD::2026-09-25']. A slot whose candidate appears there placed an order, and the
panel should say so beside the decision label rather than instead of it -- the decision really was
made in shadow mode, and the order really was sent.

### Item 5 -- the DOM fixture cannot render job rows, so nothing about them is testable

monitor/test_job_row_never_invents_a_cause.py is five tests behind a module-level skip. The reason is
in the file: the shared fixture drives the journal from the runner snapshot's day (measured: the
stubbed page requests /api/v1/job-journal/2026-08-14), and even with the day aligned a stubbed
journal renders zero .job-row nodes -- the row list is built from a filtered collection whose entry
conditions are not matched by the stub.

A fix would make a stubbed job journal render rows in monitor/test_realtime_dom.py's fixtures and
then remove the skip. Items 1, 2 and 4 all need this to be testable at the DOM level, so your
proposed ORDER should probably put it first -- say what you conclude.

Find out WHY a stubbed journal renders no rows and name the condition. "The fixture needs work" is
not an answer a reviewer can check.

If you conclude the fixture is correct and the five tests are wrong, say so and say why. That is a
legitimate finding, not a failure to deliver.

---

## 3. The gate each proposal must carry

For every item you propose to fix, your report must state the gate BEFORE any code exists. A gate is
a test that fails on today's code and passes after the change, plus -- and this is the half that gets
forgotten -- an assertion that fails if the change is applied too widely.

The second half matters for each item here, so propose it explicitly:

1. **Item 1**: the gate must distinguish THREE cases, not two -- a slot refused by a gate, a slot
   that hit WinError 1225, and a slot the scheduler never fired. A fix that merely relabels all
   "missed" rows passes a two-case test and is still wrong.
2. **Item 2**: the over-application assertion is the important one. A CLEAN run must gain NO
   diagnostic lines: assert the count for a completed job with no stderr is still zero. Without it,
   letting stdout into diagnostics floods every row on the page.
3. **Item 3**: an issue row must carry its scope, AND a row whose scope is unknown must not display
   a scope it does not have. Note that fixing this makes an existing xfail(strict=True) start
   passing, which fails the suite until the marker is removed -- name that in your proposal.
4. **Item 4**: a slot whose candidate appears in the order journal is not presented as shadow-only,
   AND a slot with no order-journal entry reads exactly as it does today.
5. **Item 5**: the five skipped tests run and pass. If you conclude the fixture is correct and the
   five tests are wrong, that is a legitimate finding -- say why.

## 4. Baselines to record in phase 1, by running them

Run these now, read-only, and put the raw counts in your report. They are the before-state that
phase 2 will be measured against, and I will re-run them.

    python -m pytest monitor/test_realtime_dom.py -q
    python -m pytest monitor/test_dashboard_backend.py -q
    python -m pytest scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py -q
    python -m pytest monitor/test_job_row_never_invents_a_cause.py -q
    python -c "import hashlib;print(hashlib.sha256(open('live_positions.track1.json','rb').read()).hexdigest())"

Expected at the time of writing, so a difference is itself information worth reporting: the first
two pass; the third is 36 passed / 1 xfailed; the fourth is 5 skipped. The hash has no expected
value -- the route is live and the book legitimately changes when a slot fills an order. Record
whatever it is.

Running pytest is reading, not writing, with one exception to respect: do NOT run the whole suite
(it takes 80 minutes and 282 unrelated failures are being triaged separately), and do not run any
script under global_index/ that connects to a broker or writes evidence.

## 5. Report format

One report, English, these sections and nothing else. No diffs applied -- proposed diffs quoted in
the report are welcome and are not the same thing.

    BASELINES         the five commands in section 4 and their raw output
    PER ITEM          for each of the five: REPRODUCED / NOT REPRODUCED / PARTIAL, the command and
                      output that shows which, the mechanism by function and line, the smallest
                      proposed change, what it would break if wrong, and the gate including its
                      over-application assertion
    FILES NEEDED      every file your proposals would touch, and any outside the phase-2 list
    ORDER             the order you would apply them in, and why
    SPEC PROBLEMS     everything in this file you believe is wrong, imprecise, or unverifiable.
                      Empty only if you genuinely found nothing -- and if it is empty, say that you
                      looked.
    NOT INVESTIGATED  anything you did not get to, with the reason

Do not run git add or git commit at any point. Do not modify production trading code. Do not delete
any parquet file or anything under data/cache/.
