# Task: rewrite the tests that pin the pre-2026-09-24 world

Read this whole file before editing anything. Everything you need is here or named here.

All output you write -- docstrings, comments, assertion messages, your final report -- in
ENGLISH only. The files you are editing are in English; do not mix languages.

---

## 1. What changed in the system, and why 65 tests went red

Until 2026-09-24 the Track 1 route could not place an order. Dozens of test files written
between 2026-08-22 and 2026-08-30 each end with a small safety section asserting that state.
Three assertions recur:

    orders are impossible                  may_enable_orders() returns False
    no order journal exists                global_index/track1_runtime/orders/ is absent
    no confirmation file exists            track1_go_live_confirmation.json is absent

On 2026-09-24 the operator ended that state deliberately. Paper orders now run inside the
session. Two orders were sent to the paper broker, both filled, and the order journal directory
now exists and holds them. The confirmation file was signed earlier, on 2026-08-27. A fourth
group pins a ROLLING seven-day pre-flight window as a literal list of dates, and that window has
simply rolled on.

So all 65 are describing a world that ended. None of them found a defect.

**Do not delete a single test.** Each one was written to protect something. Your job is to find
what rule each was protecting and assert THAT instead, so the test survives the world changing.
A deleted test is a lost invariant; a test rewritten until it merely passes is worse, because it
looks like protection and is not.

---

## 2. Your files, and only your files

The list of 52 files and the 65 test names inside them is in:

    CODEX_TASK_TEST_FAMILY_2026-09-24.filelist.txt

Edit only those 52 files, plus ONE new file you create (see section 5).

Do NOT touch anything else. In particular these are owned by another session right now:

    global_index/dash/realtime/realtime.js
    global_index/dash/shared/live.js
    monitor/backend/app.py
    monitor/backend/runner_state_reader.py
    monitor/backend/track1_runtime_reader.py
    monitor/ops.py
    global_index/track1_gates.py
    global_index/track1_account_baseline.py
    global_index/track1_paper_send.py
    global_index/track1_paper_executor.py
    global_index/run_scheduler.py
    global_index/track1_report.py
    scratch/test_track1_stage5w_paper_executor_20260825.py
    scratch/test_track1_stage5z_callsite_dryrun_20260825.py
    scratch/test_track1_stage5zzg_order_send_wire_20260827.py
    scratch/test_track1_stage5zzp_policy_rewrite_falsifiable_20260924.py
    scratch/test_track1_stage5zze_paper_account_baseline_20260827.py
    scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py
    scratch/test_track1_stage5zm_route_aware_reporting_20260826.py
    scratch/test_track1_stage5zn_planned_stop_lifecycle_20260826.py
    scratch/test_track1_stage5zw_calm_prepaper_execution_20260827.py
    scratch/test_track1_stage5zzy_dashboard_poll_no_shell_20260828.py
    TASK.md
    SCRATCHPAD.md

Also: do NOT modify any production code, do NOT run git add or git commit, do NOT delete or
rewrite any .parquet file or anything under data/cache/.

Note that four of the files in the do-not-touch list -- 5zm, 5zn, 5zw, 5zzy -- have ALREADY had
these same tests rewritten. Read them first. They are your reference implementations, and
copying their shape is the intended outcome, not plagiarism.

---

## 3. The three replacement patterns, already written and tested

These are working versions taken from the files named above. Adapt names to each file; do not
reinvent the approach.

### Pattern A -- the gate assertion

Replaces any test asserting that orders are impossible, or naming specific blockers as blocking.

Why the old form cannot be kept: the gate was closed, then open, then closed again within eight
hours on 2026-09-24 (it re-closed at 20:01 ET when the paper-account baseline passed its 24-hour
life). Any assertion pinned to one of those states is a diary entry. Note also that
PAPER_SHADOW_EVIDENCE is STILL FAILING but is no longer in blocking(), because the operator
overrode its hold on orders while leaving the measurement running -- so blocking() now
understates what is wrong, by design, and must be read together with overridden().

    from global_index import track1_gates as _G

    allowed, reasons = _G.may_enable_orders()
    if not allowed:
        assert reasons, "orders are refused and nothing on the record says why"
        return
    waived = _G.overridden()
    for b, why in waived:
        assert why, "%s proceeds under an override with no reason recorded" % b.id
    holders = [x for x in _G.BLOCKERS.values() if x.blocks_orders]
    conf = _G.current_confirmations()
    waived_ids = [b.id for b, _ in waived]
    for b in holders:
        assert (b.id in waived_ids) or b.released(conf) is True, (
            "%s holds orders and is neither released nor overridden, yet orders are allowed"
            % b.id)

Two traps here, both already paid for:

- G.BLOCKERS is a dict keyed by id, not a list. Iterate .values().
- Scope the three-state check to blockers with blocks_orders True. Eight of the twelve entries
  carry blocks_orders False and are unreleased ON PURPOSE (sleeve readiness, the bootstrap
  checkpoint, B3 freshness). That is the registry's deliberate fourth state, not a gate that
  opened quietly. Including them produces a false alarm on the one thing that is intentional.

### Pattern B -- the artefact-absence assertion

Replaces any test asserting that the order journal directory, the confirmation file, a book or a
trade log does not exist.

Absence was a usable proxy for "this suite wrote nothing" only while those paths had never
existed. Now they exist, so measure the thing the test was actually about: nothing in THIS run
wrote to them. Several of your 52 files already contain this idiom in a neighbouring test called
test_no_production_artefact_was_written_by_this_run -- use the same _IMPORTED_AT constant if the
file has one, and add it near the top if not.

    #: When this module was imported. An artefact that already exists is judged by whether it
    #: MOVED during the run, not by whether it is there.
    _IMPORTED_AT = __import__('time').time()

    ...

    for name in ("global_index/track1_runtime/orders",
                 "track1_go_live_confirmation.json"):
        p = REPO / name
        if p.exists():
            assert p.stat().st_mtime < _IMPORTED_AT, (
                "%s was written during this run; every write in this suite belongs under "
                "tmp_path" % name)

For a directory that gains files rather than changing mtime, compare a listing instead:

    def _orders_listing():
        base = REPO / "global_index/track1_runtime/orders"
        if not base.exists():
            return frozenset()
        return frozenset((str(f.relative_to(base)), f.stat().st_size)
                         for f in sorted(base.rglob("*")) if f.is_file())

    _ORDERS_AT_IMPORT = _orders_listing()

    # ... in the test:
    assert _orders_listing() == _ORDERS_AT_IMPORT, {
        "added": sorted(_orders_listing() - _ORDERS_AT_IMPORT),
        "why": "this suite wrote into the real order journal",
    }

### Pattern C -- the rolling pre-flight window

Replaces test_the_preflight_record_still_holds_the_operator_restored_seven_days and
test_the_preflight_record_is_a_rolling_real_preflight_window and anything else pinning
preflight_state.json to a literal list of dates.

The record holds a rolling seven days. It held 2026-08-17 to 2026-08-25 when those tests were
written; today it holds 2026-09-14 to 2026-09-24. Nothing is wrong. The full rewrite is already
in scratch/test_track1_stage5zn_planned_stop_lifecycle_20260826.py -- read it there rather than
from this summary. It asserts three things, and the third is the one that matters:

    exactly seven days, unique     a record that grows or repeats is not a window
    none in the future            the 5ZL incident: a day the real 13:45 ET pre-flight never set
    and the window still MOVES    newest day within 5 calendar days of the current ET session

The third is the only clause that would catch the 13:45 ET pre-flight silently stopping, because
a frozen record is indistinguishable from a healthy one by shape alone.

---

## 4. Tests that do not fit any of the three

Some of the 65 will be mixed: one assertion about the gate plus an unrelated one, or a shape you
have not seen before. Two rules:

- Rewrite only the assertion that pins the ended world. Leave every other assertion in the test
  byte-identical. If you cannot change one without changing the other, split the test into two
  and keep both names descriptive.
- If you cannot state the rule a test was protecting without inventing a requirement nobody
  asked for, STOP on that test, leave it failing, and name it in your report with one sentence
  saying why. A test left red with a reason is a result. A test made green by asserting something
  nobody decided is damage that looks like progress. You are expected to use this option; if you
  finish all 65 with no entries here, say so explicitly so it can be checked.

Also say so if you think any part of this plan is wrong. A previous delegation caught a real
defect in the spec it was given, and that was more valuable than the task itself.

---

## 5. Prove the rewrites can fail

A test rewritten until it passes is indistinguishable, from the outside, from a test rewritten
until it checks nothing. So every pattern you apply must be shown to still go red.

Create ONE new file:

    scratch/test_the_rewritten_policy_tests_can_still_fail_20260925.py

Do not name tests by position (m1, m2, sb5). Name them by the collapse they model, for example
test_a_gate_that_opens_with_no_override_recorded_is_caught.

It must contain, at minimum:

1. A healthy case that PASSES for each of the three patterns. Without this the rest proves
   nothing, because a rule that refuses everything also refuses every mutation.
2. For Pattern A: monkeypatch track1_gates.overridden to return an empty list while
   may_enable_orders still says True, and assert one of your rewritten tests raises
   AssertionError. Skip the test if the gate is currently closed, and say so in the skip reason.
3. For Pattern B: point the suite module's REPO at a tmp_path tree, seed a file, take the
   listing, add a second file, and assert the comparison fails.
4. For Pattern C: build a synthetic preflight_state.json under tmp_path, rebind REPO, and show
   that a record frozen 30 days back fails, a record with 8 days fails, and a record holding a
   future day fails.

Never mutate a production file on disk to test a mutation. The scheduler is running; a slot is
its own process and imports modules when it spawns, so a patched file on disk for even a few
seconds can reach a real run. Copy to tmp_path and rebind REPO with monkeypatch instead.

---

## 6. How to run, and what must be true when you are done

Run only the files you edited, plus your new file. Do NOT run the whole repo: a full sweep takes
80 minutes and 282 other failures are being triaged separately and are not yours.

    python -m pytest <the files you edited> scratch/test_the_rewritten_policy_tests_can_still_fail_20260925.py -q

Acceptance, all four:

1. Every one of the 65 named tests passes, or is named in your report under section 4 with a
   reason.
2. No test was deleted. For each file, the number of collected tests is the same or higher than
   before your change. Report the before and after counts.
3. Your new file passes, and its healthy-case tests are included in that count.
4. The real order journal and the position book did not change. Check before you start and again
   at the end:

    python -c "import hashlib;print(hashlib.sha256(open('live_positions.track1.json','rb').read()).hexdigest())"

   Whatever it reads when you START, it must read the same when you FINISH. Record both values in
   your report. Do NOT compare against a hash written into this file: the route is live and the
   book legitimately moves when a slot fills an order. It moved once while this file was being
   written -- the 01:25 ET NKD slot on 2026-09-25 filled MNKD and added a third position -- so a
   pinned hash here would have stopped you for the one reason that is not a problem.

   If the two values differ at the end, a test of yours wrote to the live book. Find it; the
   writes in your files belong under tmp_path.

---

## 7. Report format

One report at the end, in English, with these sections and nothing else:

    FILES EDITED        one line per file: path, tests before, tests after
    TESTS REWRITTEN     one line per test: name, which pattern (A/B/C/other), one clause on
                        what rule it now asserts
    LEFT FAILING        one line per test you stopped on, with the reason
    MUTATIONS           one line per mutation in your new file: what it breaks, which test
                        catches it
    BOOK HASH           the two hashes, start and end
    PLAN PROBLEMS       anything in this file you think is wrong, or empty
