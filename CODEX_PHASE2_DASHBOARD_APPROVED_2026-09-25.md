# PHASE 2 (APPROVED): implement the five dashboard corrections

The Phase 1 report was cross-checked against the repository. Verdicts and the approved correction
for each item are below. Two of your findings changed the plan; one of them corrected a wrong
diagnosis in the original specification, and it is recorded as yours.

All output in ENGLISH only. Do not run git add or git commit. Do not restart the scheduler.

---

## 0. Cross-check verdicts

| Item | Your finding | Verdict |
|---|---|---|
| 1 | reproduces | CONFIRMED |
| 2 | reproduces, spec mechanism incomplete | CONFIRMED, with one refinement you missed -- see 2.1 |
| 3 | reproduces | CONFIRMED |
| 4 | reproduces | CONFIRMED |
| 5 | spec diagnosis wrong, trailing slash is the cause | CONFIRMED -- the specification was wrong, you were right |

Independent re-measurements that settled the two disagreements:

Item 5. The base fixture does carry a trailing-slash key, and the longest-prefix sort makes it win:

    python -c "from monitor.test_realtime_dom import BASE_PAYLOADS; print('/api/v1/job-journal/' in BASE_PAYLOADS, '/api/v1/job-journal' in BASE_PAYLOADS)"
    -> True False

A two-case browser probe, written here rather than taken from your report:

    NO SLASH   rows=0
    WITH SLASH rows=1  09-25, 01:10 ET 2s + RUNNER RECOVERED TRACK1_NKD_0110
                       This execution failed and a later slot ran clean: exited with code 2.

The original specification's claim that journalJobs() filters the supplied jobs is also false;
journalJobs() only sorts. Both spec errors are withdrawn.

Item 2. The exit line does precede the child echo, and the job is popped from active on it:

    global_index -> monitor/backend/job_journal_reader.py, the exited-with-code branch:
        _finish(current, timestamp, "failed", ...)
        active.pop(job_id, None)

so every later stdout AND stderr line for that job_id meets current is None and is dropped.
Confirmed.

### 2.1 The refinement you missed, and it changes your gate

Your report implies diagnostics are empty because all child output is dropped. That is true for
those five NKD jobs but not in general. Measured on the same day:

    python -c "from pathlib import Path; from monitor.backend.job_journal_reader import read_job_journal; d=read_job_journal('2026-09-25', Path('.')); print([(j['job_id'], len(j['diagnostics'])) for j in d['jobs'] if j.get('diagnostics')])"
    -> [('ANCHOR_CHECK_0055', 1), ('TRACK1_STOP_REPAIR_1020', 4)]

Two jobs DO carry diagnostics today. They arrive by a different branch: an ERROR or CRITICAL line
that is NOT prefixed stdout: or stderr: and arrives while the job is still active. A job that
"completed OK but wrote CRITICAL/ERROR" has its loud lines echoed before its terminal line, so it is
still active when they land.

So your fix must not disturb that path, and your over-application gate is stronger if it pins those
numbers rather than only asserting zero on a clean job. See gate G2.2.

---

## 1. Phase 2 file permissions -- exact

You may MODIFY only these:

    monitor/backend/job_journal_reader.py
    monitor/backend/track1_market_view.py
    global_index/dash/realtime/realtime.js
    monitor/test_job_row_never_invents_a_cause.py
    scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py    ONE marker only -- see item 3
    plus NEW test files you create under monitor/

You may READ anything.

You may NOT modify, for any reason, including "it would be a one-line improvement":

    monitor/test_realtime_dom.py        the shared fixture is correct; item 5 is a caller bug
    global_index/track1_signals.py      its vocabulary is read by gates
    global_index/track1_signal_layer.py
    global_index/run_live_day_track1.py
    global_index/runner.py              under live investigation -- see section 4
    global_index/run_maxhold_exit.py    same
    global_index/run_stop_repair.py     same
    global_index/track1_paper_send.py
    global_index/track1_gates.py
    monitor/ops.py
    TASK.md  SCRATCHPAD.md
    live_positions.track1.json and anything under global_index/track1_runtime/

If a fix appears to need a file outside the modify list, stop on that item and report it. Do not
widen the list yourself.

Three of the later items have an obvious tempting route outside this list; the answer is decided, so
you do not have to ask:

  * Item 9 could be solved by writing a stop_deferred flag into the route's position book. That is
    the route's writer and it is NOT yours. Compute the deferral on the page from entry_time and
    sleeve instead, and say in your report that you did.
  * Items 8 and 10 may need a field the backend does not serve yet. monitor/backend/
    track1_market_view.py and job_journal_reader.py are already in your modify list; nothing else
    in monitor/backend/ is. If you need a third reader, stop and report.
  * No item justifies touching global_index/runner.py. The arming rule lives there and a separate
    task is already open against it.

---

## 2. Approved correction per item

### Item 1 -- approved as you proposed, with one constraint added

Read the day's job journal once in build(), index Track 1 jobs by job_id, pass the index into
_slots_for(). Add a distinct status for "fired and produced no decision record". Keep missed for a
slot with no matching job at all. Carry that job's own reason.

Added constraint: match on job_id AND the session date. Your own risk note named repeated job IDs
attaching yesterday's reason; make that impossible rather than unlikely.

### Item 2 -- approved as you proposed, plus the refinement in 2.1

One capped child-diagnostic attachment helper. Target the active execution or the most recent failed
execution of the same job_id. Keep child text out of launch detection. Retain failure output only.
Enforce _MAX_CHILD_DIAGNOSTICS. Add a refusal-evidence branch in _annotate_impact_and_action()
before the unclassified fallback.

Note for your impact classifier: the refusal text to recognise is on stdout and reads

    REFUSED - order sending was requested and is not available:
    Nothing was run. Re-run without --allow-orders for a shadow pass.

and the Gateway case is a stderr line containing WinError 1225. Classify those two distinctly. Do
not add a classifier for NameError or any other Python exception -- a source defect is not an
operational category and should stay unclassified.

### Item 3 -- approved

Add one scope badge per issue row using issueScope(issue.route_scope), with an explicit
unknown-scope rendering rather than an empty chip. Remove only the xfail marker in the 5ZZH file.

### Item 4 -- approved as you proposed

Read track1_report.read_order_journal(root) once in build(). Compare each signal candidate's full
dated trade_id against filled_trades. Add a separate structured execution field. Keep the
decision-layer reason unchanged and render both facts together.

### Item 5 -- approved, and it is a one-line change

Change _stub() in monitor/test_job_row_never_invents_a_cause.py to override
/api/v1/job-journal/ with the trailing slash, then remove the module-level skip. Do not touch
monitor/test_realtime_dom.py.

---

## 3. Additional gates required

These are on top of the gates in your report. Each one exists because a specific way of getting this
wrong has already happened in this repository.

**G1 (item 1) -- the three-way distinction must be asserted on three DIFFERENT inputs.** A test that
feeds one synthetic log and checks one label passes with a fix that relabels everything. Assert: a
stdout gate refusal, a stderr WinError 1225, and a slot with no launch line, in one test, with three
different expected strings.

**G2.1 (item 2) -- a clean completed job with no stderr stays at exactly zero diagnostics.** As you
proposed.

**G2.2 (item 2) -- the two jobs that carry diagnostics today keep their exact counts.** Pin
ANCHOR_CHECK_0055 at 1 and TRACK1_STOP_REPAIR_1020 at 4 against the real 2026-09-25 journal, or
build synthetic equivalents of the same shape. This is the assertion that catches your change either
flooding that path or breaking it. G2.1 alone does not.

**G3 (item 3) -- an unknown scope must render a visible unknown, not an empty chip and not a
guess.** Assert with a payload whose route_scope is absent and one whose value is not in the map.

**G4 (item 4) -- matching is on the full dated trade_id.** Assert that a candidate with the same
sleeve and instrument but a DIFFERENT date is not marked as having filled.

**G5 (item 5) -- assert the stub was actually used.** After fixing the key, add an assertion that
the rendered row count is non-zero BEFORE asserting anything about its text. The five tests failed
for a month while appearing to test row text, because a silently unmatched stub returns an empty
journal and every text assertion then passes over an empty list. This is the same shape as asserting
over a list nobody checked was non-empty.

**G6 (all items) -- no change may write to the live route.** Record this at the start and the end of
your run and report both values; they must match, whatever they are:

    python -c "import hashlib;print(hashlib.sha256(open('live_positions.track1.json','rb').read()).hexdigest())"

Note the value has changed twice since the specification was written. It is a live file. Compare
your own two readings, never against a number in a document.

**G7 (all items) -- the three named suites keep or improve their counts.** Baselines you measured,
which I re-measured and agree with:

    monitor/test_realtime_dom.py                                   88 passed
    monitor/test_dashboard_backend.py                              225 passed
    scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py    36 passed, 1 xfailed -> expect 37 passed
    monitor/test_job_row_never_invents_a_cause.py                  5 skipped -> expect 5 passed

---

## 4. One thing you must know, and must not touch

While cross-checking your book-hash gate, that gate did its job and surfaced a live incident: the
route's position book was emptied this morning while the broker still holds three positions, none of
them with a stop. The mechanism is a field-name mismatch in a legacy reader being handed the Track 1
book, and the warning that would have reported it is logged at WARNING level, below the scheduler's
ERROR filter -- so both jobs involved reported "completed OK".

Three consequences for you:

1. global_index/runner.py, run_maxhold_exit.py and run_stop_repair.py are under live investigation
   and are on your do-not-modify list. Do not "fix" the field-name mismatch you may notice there.
2. Your item 2 fix does NOT catch this, because the swallowed line is a WARNING, not ERROR or
   CRITICAL. Do not widen your change to admit WARNING as part of item 2. If you believe WARNING
   admission is warranted, report it as a separate proposed item with its own volume measurement --
   how many WARNING lines a normal day would add to every row.
3. The live book may change under you while you work. That is expected. G6 compares your two
   readings, not a fixed value.

---

## 5. Report format for Phase 2

    PER ITEM          item number, files changed, the diff summary, and the measurement showing it works
    GATES             G1 through G7, G8.x, G9.x, G10.x, G11.x and G12.x, each with PASS/FAIL and the command
                      and output. G8.x belong to item 6, which was added after approval -- see
                      section 6. TEN items, not five.
    TESTS             the four suites in G7, counts before and after
    BOOK HASH         your two readings
    NOT DONE          anything left, with the reason
    NEW FINDINGS      anything you noticed and did not touch, especially in the do-not-modify files

---

## 6. Item 6 -- ADDED AFTER APPROVAL, 2026-09-25 12:4x ET

Read this even if you already started. It is a sixth item in the same defect family as the other
five, found while answering a question about the positions panel.

### What is wrong

Each open-position card carries four fact blocks: OPENED, HELD, RISK BUDGET and STOP ORDER. Two of
them are blank even when the book is full.

Measured at 01:xx ET this morning, when the route's book held three positions:

    OPENED        2026-09-24, 09-24 17:55 ET      filled
    HELD          --d                             blank, with the book present
    RISK BUDGET   --                              blank, with risk_dollars = 469.4643 in the row
    STOP ORDER    --                              blank

The cause is the same dialect split as the rest of this list, this time between the PAGE and the
BOOK. The page reads

    runner?.days_held        and        runner?.risk_sized

Those two names belong to the dashboard snapshot the legacy runner writes, which computes days_held
itself and spells the risk field risk_sized. The route's position book carries neither: it has
entry_time and risk_dollars. The bridging helper in realtime.js maps four names -- instrument to
inst, sleeve to cluster, qty to contracts, entry_time to entry_day -- and misses these two.

Confirm it yourself before changing anything:

    python -c "import json; d=json.load(open('live_positions.track1.json.before_qty_repair_20260924_232859',encoding='utf-8')); print(sorted(d['positions'][0]))"

and find the two reads in global_index/dash/realtime/realtime.js near the fact-held and fact-risk
blocks.

### Why it is separate from the book being empty

The book is empty right now for an unrelated reason, so all four blocks are blank today. Restoring
the book will fill OPENED, the entry price, the stop and the percentage move. It will NOT fill HELD
or RISK BUDGET, because those two are a mapping gap and not a data gap. Do not report the item as
fixed by observing the live page after a restore.

### The approved change

Extend the bridging helper, not the call sites. Derive a holding age from the book's entry_time, and
read risk_dollars when risk_sized is absent. Keep every existing mapping untouched.

### Gates

**G8.1** HELD renders a NUMBER derived from the book's entry_time. Assert the number, not merely that
it is not a dash.

**G8.2** RISK BUDGET renders the book's risk_dollars when risk_sized is absent.

**G8.3 -- the over-application guard.** A row that DOES carry risk_sized must render exactly what it
renders today. The dashboard snapshot shape must not start being reinterpreted; this change adds a
fallback, it does not change a source of truth.

**G8.4** A row carrying neither risk field must render an explicit not-recorded, NOT a zero. A zero
in a risk column reads as "no risk was allocated", which is a claim the data does not make. Same for
a holding age that cannot be derived.

**G8.5** The two panels that already pass must keep passing: monitor/test_realtime_dom.py at 88 and
monitor/test_decision_panel_reads_track1_series.py at 8.

---

## 7. Item 7 -- ADDED 2026-09-25 12:5x ET, after the position book was restored

### What is wrong

The page matches a book position to a broker position by reducing both symbols to a root. Run on the
three symbols actually in play:

    M2KZ6  ->  M2K     matches the book's M2K
    MYMZ6  ->  MYM     matches the book's MYM
    MNKZ6  ->  MNKZ    does NOT match the book's MNKD

rootOf special-cases anything starting with NKD or MNKD, and the roots list contains MNKD. IBKR's
micro Nikkei symbol is MNK plus a month letter, so MNKZ6 matches neither, falls through to the digit
strip, and becomes MNKZ.

Measured on the live page immediately after the book was restored: M2K and MYM rendered matched with
their sleeve and open date; MNKD rendered "runner unmatched UNKNOWN" with a blank OPENED. Confirmed
by running rootOf against those six strings directly.

The system already knows the right answer: the order journal row for that fill carries
tradable_symbol MNK.

### Why it is not cosmetic

That match drives the unprotected-position display and the runner-against-broker reconcile on the
page. While it fails, the page cannot show a stop for that instrument even after a stop is placed --
so the 16:20 ET stop placement could succeed and the page would still show the position bare.

Note the scope: only the dashboard is affected. The endpoint the page reads serves the raw broker
symbol MNKZ6, while the runner's own broker read normalises to MNKD, so the safety sweeps match
correctly. Do not change either broker reader.

### The approved change

Teach rootOf the MNK family, in the same explicit way NKD and MNKD are already handled. Do not
rewrite the general fallback.

### Gates

**G9.1** rootOf('MNKZ6') resolves to MNKD, and so does every month letter, not just Z.

**G9.2 -- the over-application guard.** rootOf returns exactly what it returns today for every other
symbol in play: M2KZ6, MYMZ6, MESZ6, MNQZ6, M2K, MYM, MNKD, NKDZ6. Assert the full table, measured
before your change.

**G9.3** A symbol belonging to no known root still falls through to the existing fallback and is not
matched to anything. A mapping that guesses is worse than one that abstains.

**G9.4** A DOM assertion: with the book holding MNKD and the broker serving MNKZ6, the card renders
the sleeve and the open date rather than "runner unmatched".

---

## 8. Item 8 — the job that protects open positions appears on no bar

### Measured, 2026-09-25 13:57 ET

At that moment the route held three positions and none of them had a working stop. The schedule bar
read:

    NEXT JOB       TRACK1_SWING_1405   14:05 ET   in 7m
    NEXT DECISION  SPY_REFRESH_PM      18:20 ET   in 4h 22m

The 16:20 ET stop-repair sweep appears nowhere, and it is the only job before 18:20 that can place a
stop behind those three positions.

Repeat it with:

    python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:5002/api/v1/schedule-status')); print(d['next_scheduled_job'], d['next_decision_job'])"

### Mechanism

Two fields feed two bar slots. next_scheduled_job is simply the soonest job of any kind.
next_decision_job is a filtered category that does not include the safety sweeps.

The Rổ 4 window has a slot every five minutes from 14:05 to 15:55 — twenty-three of them — so
next_scheduled_job is occupied by a swing slot for the whole afternoon. The sweep can only become
"next job" after 15:55, roughly twenty-five minutes before it runs.

So the job that protects open positions is surfaced only when it happens to be soonest by the clock.
It belongs to neither category, and on the afternoon it mattered most it was invisible.

### Which jobs can place a stop, since this is easy to get wrong

Only a job that constructs the legacy runner can arm a stop — the B4 check runs inside its
constructor. On this route that is:

    run_maxhold_exit     09:31 ET, once a day
    run_stop_repair      the sweeps: 00:20 04:20 06:20 08:20 10:20 16:20 18:20 20:20 22:20 ET

The 14:05 slot does NOT place stops. It runs a different entry point that never builds that runner.
This was stated wrongly once during the incident and corrected; a fix here should not repeat it.

### Direction a fix would take

When the route holds a position with no working stop, the bar must name the next protection job and
its time. Adding a third reading, not repurposing either existing one.

### Gates

**G10.1** With open positions and no working stops, the bar names the next sweep and its ET time.

**G10.2 — the over-application guard.** With every open position protected, or with an empty book,
the bar reads exactly as it does today. This adds a reading for a state that currently has none; it
does not change the two that exist.

**G10.3** NEXT JOB keeps meaning "soonest job of any kind". A fix that promotes the sweep into that
slot would make the bar lie about what runs next.

**G10.4** The arming rule is per sleeve and must not be restated on the page: Rổ 4 arms at 14:00 in
New York the day after entry, NKD at 14:00 in Tokyo the day after entry. A position still inside its
deferral window is not unprotected and must not be counted as needing a stop. Assert both sleeves,
with a position on each side of its own arming time.

---

---

## 9. Item 9 — a deferred stop is counted as a naked one

### Measured, 2026-09-25 14:00 ET

The exposure tile read:

    Protection   0 covered / 3 naked

At that instant M2K and MYM had just passed their arming time, 38 seconds earlier, so naked was
correct for them. MNKD had eleven hours still to run before its own arming time and was counted
naked as well. The honest reading was 2 naked, 1 deferred.

Worse in the other direction: between 15:55 the previous day and 14:00 that afternoon, ALL THREE
were inside their deferral windows and the tile read 3 naked for twenty-two hours. An alarm that
stands for a whole day on a normal state is an alarm people learn to scroll past.

### Mechanism

The page already distinguishes three states — covered, deferred, naked — and decides deferred by
reading a stop_deferred flag on the matched book row. The route's book rows do not carry that
field. Measured: the twenty-one keys on a restored row include stop_price and stop_basis and no
stop_deferred. So every row falls through to naked.

MNKD fails twice over: it is also unmatched (item 7), so the deferred lookup finds no row at all.

### Direction a fix would take

The deferral rule already exists in the runner and is per sleeve: Rổ 4 arms at 14:00 New York the
day after entry, NKD at 14:00 Tokyo the day after entry. Either carry the computed flag into the
book row, or compute it on the page from entry_time and sleeve. Carrying it is cheaper to read but
goes stale in the file; computing it cannot go stale but restates the rule in a second language.
State which you chose and why.

### Gates

**G11.1** A position inside its deferral window counts as deferred, not naked.

**G11.2** A position past its arming time with no working stop still counts as naked. This is the
assertion that stops the fix from simply silencing the tile.

**G11.3** Both sleeves, with a position on each side of its own arming time — four cases. Rổ 4 uses
New York, NKD uses Tokyo, and a fix that applies one clock to both passes a two-case test.

**G11.4** A position that cannot be matched to a book row at all is NOT quietly counted as deferred.
Unknown is not safe. It must read as unknown.

---

## 10. Item 10 -- the live numbers are dimmed as if they were a month old

### Measured, 2026-09-25 19:3x ET

The whole money band renders at 42 per cent opacity. The container carries a runner-stale class, and
the stylesheet dims every element tagged runner-derived inside it.

The condition driving it is honest and the rule is right: the LEGACY runner's state file is 784
hours old -- 32 days -- because that route is retired and nothing writes the file any more. Anything
derived from it should be dimmed, and the rule exists because of a real incident: the endpoint once
reported a payload 80 hours old as fresh, so the block read as live when it was not.

What is wrong is which elements wear the tag. Measured element by element, with computed opacity:

    0.42   PAPER EQUITY    USD 251,752, baseline PASS read 5.47h ago, broker now 251,882
    0.42   Gross           4 held
    0.42   Realized today / Sharpe / Calmar / RISK      all showing --
    1.0    Open UPL        +$453
    1.0    Positions / Working orders / Protection      4 / 4 / 4

PAPER EQUITY and Gross are sourced from the paper account, the broker and the Track 1 book. All
three are current. They are being drawn at the opacity reserved for month-old data, and the tile
says so itself while it is dimmed: it prints a broker figure read minutes ago.

The other four dimmed cells are empty for a different and legitimate reason -- no position has
closed, so there is no realised P&L to compute from. They are dim for the wrong reason but they do
not mislead, because there is nothing behind them to misread.

### Direction a fix would take

Re-tag. An element derived from the paper account, the broker or the Track 1 book is not
runner-derived. Do not touch the dimming rule or the staleness condition.

### Gates

**G12.1** With the legacy runner stale, PAPER EQUITY and Gross render at full opacity.

**G12.2 -- the guard that keeps the rule worth having.** An element that IS derived from the legacy
runner still dims when that state is stale. A fix that merely removes the dimming is the incident
the rule was written after, re-created. Assert at least one element on each side.

**G12.3** When the legacy runner state is fresh, nothing in the band is dimmed.

**G12.4** The staleness condition itself is unchanged: it reads the envelope's own age, not the
schedule's opinion of whether a publish was due. That distinction was measured and paid for once --
a payload 80 hours old reported as fresh -- and must not be undone while re-tagging.
