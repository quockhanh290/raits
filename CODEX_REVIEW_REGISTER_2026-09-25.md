# Review register — Track 1 go-live defects, 2026-09-24 to 2026-09-25

One row per finding. The point of this file is that nothing closes on a report: a row moves to
VERIFIED only when someone re-ran the measurement themselves and says so in the last column.

Status vocabulary, used strictly:

    FIXED-VERIFIED    changed, and the fix re-measured by someone other than whoever made it
    FIXED-REPORTED    changed, and only the changer has measured it
    IN PROGRESS       a Codex run is live on it right now
    SPEC READY        written up with gates, nobody started
    NEEDS DECISION    the work is understood; an operator has to choose before anyone writes code
    RECORDED          measured and written down, not yet specified
    NOT A DEFECT      looked wrong, is not, reason given

Severity is ordered by what it could cost, not by how hard it is to fix.

---

## A. The live order path

| ID | Finding | Severity | Status | Owner / spec | Closing gate |
|---|---|---|---|---|---|
| A1 | The kill-switch file stops nothing. STOP_TRADING.track1 is printed at run_live_day_track1 line 2084 and reported into a summary dict at 1920. observe_live_slot — the path the scheduler runs, and the path that calls maybe_send_orders — never reads it. The printed sentence says "no entries would be taken" | highest: it is the mechanism of last resort, and the working control today is stopping the scheduler | RECORDED | unassigned | creating the file must make a slot refuse to send, re-read at send time and not only at process start; and the message must not claim an enforcement that is not there |
| A2 | An unreadable book is converted to an empty book. The legacy loader catches every parse error, logs a WARNING, and sets loaded_positions to empty. Both safety jobs build that loader against the Track 1 book | highest: it happened. Three positions lost their record and their stops on 25/9 while two jobs reported completed OK | NEEDS DECISION | PROPOSAL_UNREADABLE_BOOK_MUST_NOT_READ_AS_EMPTY_2026-09-25.md | a book that exists and cannot be parsed raises; a missing file still loads as empty; the file is byte-identical after a failed load |
| A3 | The circuit breaker runs on a constant. Every slot is a new process building a new Track1Book whose equity defaults to the 50,000 account figure; nothing on the live path restores equity, peak or day-start from the file, and all three are 0.0 on disk after four real fills | high: it can log a verdict and can never trip on accumulated drawdown | RECORDED | unassigned | the breaker's input is a measured figure; and a synthetic drawdown past the limit makes it refuse |
| A4 | The B3 broker/book mismatch halt does not reach Track 1. The flag lives on the safety job's own runner object; observe_live_slot never constructs one | high: on 25/9 B3 found three orphans and Track 1 kept deciding | RECORDED | unassigned | a recorded mismatch must block new entries on this route, and a clean reconcile must not |
| A5 | entry_day does not survive the book dialect, so every position loads with no entry date and the deferral rule answers not-deferred — stops arm immediately. Measured: the 16:20 sweep armed MNKD nine hours early and MES twenty-two | high: this is the divergence already measured at roughly 53,000 dollars once and fixed | SPEC READY | CODEX_TASK_ENTRY_DAY_DIALECT_2026-09-25.md | the four real rows split two due, two deferred, against a fixed clock; a row with no date at all still loads None and still reads not-deferred |
| A6 | The order gate is read once at process start and never re-read at send. The live path never calls overridden(), so an override is invisible to everything except ops status | medium: an approval revoked mid-session still sends; and the record cannot tell waived evidence from produced evidence | RECORDED | unassigned | both factors re-read at the send, and any printed gate answer carries its overrides |
| A7 | The audit artifact states "no gate blocker is open — an order would not have been refused" while PAPER_SHADOW_EVIDENCE is failing and overridden | medium: it is the sentence a reader will trust in December | RECORDED | with A6 | the artifact names the override and its measurement, or does not claim the gate is clear |
| A8 | read_route_positions turns two malformed shapes into a partial answer: a book with no positions key returns empty, and non-dictionary list elements are dropped silently. Measured: 1 real row plus 2 junk elements returns 1 row with no complaint | medium: it is the A2 family, in the function written to prevent A2 | RECORDED | mine, small | both cases raise; a genuinely absent file still returns empty |
| A9 | Position sizing divides by the 50,000 design figure, not measured equity. Contract counts are fixed per sleeve | low, possibly none | NOT A DEFECT pending confirmation | operator | if it is the validated-capital model, say so where it is displayed; it must not be described as live-equity sizing |
| A10 | A failed max-hold run has no same-day retry; the position stays open until the next day's run | low | RECORDED | unassigned | a failed run is visible as failed and the overdue position is named |

---

## B. Already fixed on the live path

| ID | Finding | Status | Verified by |
|---|---|---|---|
| B1 | The legacy row reader demanded inst/contracts/cluster and raised on every Track 1 row, which is the mechanism behind A2's 25/9 incident. Reader now accepts both dialects; writer emits both | FIXED-VERIFIED | Codex made it; I re-ran all gates myself — 10 rows across 8 books load, fail-closed preserved, conflicting values raise, round trip through the three Track 1 readers passes |
| B2 | The same change broke T7.4, which asserted the persisted row is exactly the model's fields. Aliases are now declared in one constant that both the writer and the test read, and the test gained an assertion that an alias carries its field's value | FIXED-VERIFIED | mine; test_operational_fixes back to 39 passed |
| B3 | advance_book read cand.contracts, a field the Candidate does not have, and wrote qty 0 for every fill. The MNKD row was booked at size zero against a broker holding one | FIXED-VERIFIED | mine; 9 tests, including one that forbids any zero-size row reaching the book |
| B4 | The live slot built its book empty, so duplicate-entry suppression, the cluster caps and exit settlement were all blind to positions opened by earlier slots | FIXED-VERIFIED | mine; measured live — slot 14:05 recorded held_at_decision 3, and the caps now compute against four real rows |

---

## C. The dashboard

Ten items, cross-checked from a Phase 1 report, approved, and handed over as one run.

| ID | Item | Status |
|---|---|---|
| C1 | Market view "missed" collapses "never fired" with "fired and died" | IN PROGRESS |
| C2 | The job journal keeps only stderr, so the child's stdout reason is lost and the impact falls to "unclassified error" | IN PROGRESS |
| C3 | issueScope has no caller; no issue row says whose problem it is | IN PROGRESS |
| C4 | A slot that placed a filled order is labelled shadow only | IN PROGRESS |
| C5 | The DOM fixture: a stub key missing its trailing slash, not a fixture defect | IN PROGRESS |
| C6 | HELD and RISK BUDGET blank because the page reads days_held and risk_sized while the book writes entry_time and risk_dollars | IN PROGRESS |
| C7 | MNKZ6 reduces to MNKZ and never matches the book's MNKD | IN PROGRESS |
| C8 | The job that protects open positions appears on neither bar slot | IN PROGRESS |
| C9 | A deferred stop is counted as naked; the tile read 3 naked for twenty-two hours of normal state | IN PROGRESS |
| C10 | The live money band is dimmed at legacy-staleness opacity while showing fresh figures | IN PROGRESS |

All ten are in CODEX_PHASE2_DASHBOARD_APPROVED_2026-09-25.md with gates G1 through G12.4. Baseline
before the run, to compare against: test_realtime_dom 88 passed, test_dashboard_backend 225 passed,
5ZZH 36 passed and 1 xfailed, test_job_row 5 skipped, test_decision_panel 8 passed. A fingerprint of
the seven files that run may touch was taken before it started.

Already fixed on the dashboard, both mine, both verified on the live page before and after:

    the decision panel rendered nothing because it read snap.decision while the Track 1 series
    carries opens and closes
    the job row asserted "Windows denied the runner-state publication" for every recovered job,
    regardless of why it failed

---

## D. Reviews outstanding

| Review | Scope | Status |
|---|---|---|
| Paper tab | fill quality and slippage, account and book reconciliation, the fifteen NOT_WIRED rows, absent versus zero | SPEC READY — CODEX_TASK_PAPER_TAB_REVIEW_2026-09-25.md |
| Risk layers | returned and cross-checked; findings are rows A1 to A10 above | DONE |

---

## E. Decisions waiting on the operator

| Decision | What hangs on it |
|---|---|
| The C1 slippage gate: cost or correspondence | It currently uses an absolute mean, so a fill better than the signal price counts as a breach. The spec's own rationale is written entirely in cost terms. Four fills are inside the modelled cost on every one, and the gate reads QUALITY_BREACH |
| A2, the unreadable book | Written up with gates. Nothing proceeds on it without a yes |
| The paper account baseline | It expires 24 hours after recording and no job refreshes it. When it lapses the order gate shuts and the night's slots run shadow-only |
| A9, sizing against design capital | Whether it is the intended model. If it is, the displayed wording needs to match |

---

## F. What this register is for

Two rules, both bought with real incidents this week.

A report is not a measurement. A session reported four failing tests in one file; re-running found
them in a different file with the original passing 10 of 10. Another published a cause taken from a
printed counter rather than from the code; reading the code showed the opposite. Every row above
that says VERIFIED names who re-measured it, and it is never the same person who wrote the fix.

A fix is not closed until its over-application guard exists. Most of the gates in the linked specs
come in pairs: the assertion that the defect is gone, and the assertion that the fix did not reach
further than the defect. The second half is the one that gets dropped, and it is the half that stops
a fix from being a silencer.

---

## G. Round update, 2026-09-25 evening — two reports merged

### Dashboard Phase 2: reported complete, partially verified by me

Codex reports all ten items done with gates G1 to G12.4 passing. What I re-measured myself:

    item 3   the strict xfail marker is gone from the 5ZZH file            CONFIRMED
    item 5   the module-level skip is gone from the job-row test file      CONFIRMED
    item 2   job_journal_reader now classifies WinError 1225 and handles
             late child output attached to the most recent failed run      CONFIRMED by content

Not yet re-measured by me: the suite counts, the DOM assertions, and items 1, 4, 6 to 10. Those stay
FIXED-REPORTED until someone re-runs them. The register's own rule applies to this row.

A caution worth recording: I compared file fingerprints taken before the run and concluded three
files were untouched. They had been changed. The baseline was taken while the run was still writing.
Content checks settled it, and the fingerprint method is not evidence unless both ends are quiet.

### Paper tab review: new findings, cross-checked

| ID | Finding | Verified by me |
|---|---|---|
| N1 | The tab reports BREACH, 0 of 4 protected, while the broker holds four working stops. It checks for a stop_order_id field the route's writer never fills | YES — no book row has stop_order_id, all four have stop_price, and the broker log shows four PreSubmitted STPs |
| N2 | paper_evidence_reader expects inst, cluster, contracts, so protection rows lose instrument, cluster and size. Sixth instance of the dialect family | not re-measured; consistent with five confirmed instances |
| N3 | Fifteen NOT_WIRED rows split three ways: six have a source nobody reads, two are read and then discarded, seven are genuinely missing | not re-measured row by row |
| N4 | The readiness card reads obsolete flat properties, so it shows undefined targets and PENDING instead of the gate's real verdict | not re-measured |
| N5 | The payload carries a superseded spec string beside the active one | not re-measured |
| N6 | day None on the aggregate execution-quality endpoint is deliberate and no in-scope reader compares it to a date | NOT A DEFECT — this retires the concern I raised |

### A correction to my own earlier finding

C1's absolute value is deliberate and documented. The spec carries use_absolute true with its own
rationale: a fill four ticks better than its reference is still a four-tick error in the expected
fill price, and the model that sizes risk from that reference is wrong by the same amount whichever
way the miss falls.

I had read only the threshold rationale, found it written in cost terms, and concluded the absolute
comparison did not implement the spec. That conclusion is withdrawn. The remaining defect is the
label: QUALITY_BREACH reads as a cost verdict on a gate that measures correspondence.

This also closes the decision in section E: there is nothing to decide. The maths was never the
question.

### Where the work went

Everything above is planned in PLAN_ADDRESS_FINDINGS_2026-09-25.md as two batches partitioned by
file, plus the items that cannot be delegated: A2 needs a decision, A5 has its own spec, A9 needs a
confirmation, and the genuinely-missing evidence sources are a build decision rather than a fix.

---

## H. Status as of 2026-09-25, late evening

Every VERIFIED row below was re-measured by me, not by whoever made the change.

### Closed

| Ref | What | Verified how |
|---|---|---|
| A5 | entry_day, in three parts. The swing setup no longer discards the date; the reader derives entry_day from a date-bearing entry_time and refuses to guess from a bare clock | I ran all seven baseline suites plus the new file myself: 8, 39, 53, 10, 19, 3, 5 and 9 — identical to the pre-change baselines, nothing new red. And I ran the four real rows through the changed reader against a fixed 16:30 ET clock: M2K and MYM due, MNKD deferred, MES not-deferred with an absent date rather than a guess. That is the first time the deferral rule has been able to see anything on this route |

Note what A5 does NOT do: the four existing rows keep whatever they have. Only positions opened
after the change carry a dated entry_time from the start. MES stays undeferrable until its row is
repaired, which is Part 3 and is the operator's to run.

Also measured and worth keeping: an already-placed stop is never cancelled when a position becomes
deferred. Deferred positions are excluded from the only branch that inspects or places a stop, and
there is no cancellation branch. So MNKD's early stop stays working. The fix was safe to land at any
hour, which is why it did.

### Open, with a defect of its own

| Ref | What | State |
|---|---|---|
| Batch 2 | The paper tab now reconciles protection against broker positions and working STP orders, in three states; the book dialect falls back; eight NOT_WIRED rows were wired; the C1 label reads as correspondence rather than cost; zero and absent render differently | FIXED-REPORTED. One real over-application found by me, still open |

The over-application: with ZERO persisted positions and an unreadable broker, the tab now renders
UNKNOWN. It should render 0 of 0. With no positions there is nothing to protect and that is knowable
without the broker, so UNKNOWN there is a false uncertainty — the same defect family as the one the
batch fixed, pointed the other way.

test_an_empty_book_is_not_reported_as_unprotected catches it and is still red. That test is not
obsolete: it was written after three panels each answered the empty-book case differently and it
carries a control assertion beneath it. The gate I wrote said "when the broker cannot be read, say
unknown" and was missing the clause "unless there is nothing to protect". My omission, third of the
same kind today.

Unmeasured: the batch ran two suites of its own and the C1 arithmetic tests. It did not run
test_paper_dom.py or test_dashboard_backend.py, so the regression surface is unknown. The red test
above surfaced because I ran it, not because the batch's own gates caught it.

### Ready, nobody started

| Ref | What | Blocked on |
|---|---|---|
| Batch 1 | Kill switch not enforced, breaker on a constant, B3 halt out of reach, two flaws in my reader | Nothing. It was waiting on A5 releasing track1_signal_layer.py, and A5 is closed |
| Batch 2 correction | The empty-book clause, plus the two suites | Nothing |
| A5 Part 3 | Repair the MES row from the order journal | The proposal is in the V2 report; I have not read or checked it yet |

### Still the operator's

| Ref | What |
|---|---|
| A2 | An unreadable book answered as an empty book, in the loader both safety jobs use. The proposal is written with its gates. This is the one that has already cost us |
| A9 | Sizing divides by design capital. If that is the validated model, the wording must match |
| the genuinely missing evidence sources | seven NOT_WIRED rows have no source at all; building them is a decision, not a fix |

### Dashboard Phase 2

Ten items reported complete. I confirmed three by content: the strict xfail is gone, the module skip
is gone, and the journal reader classifies WinError 1225. The remaining seven and all the suite
counts stay FIXED-REPORTED until someone re-runs them.

---

## I. Batch 1, re-measured by me — 2026-09-25 late evening (ET 23:35 Fri)

Batch 1's own suite: 10 of 10 green, run by me. The wider regression over every suite that
imports either changed module (75 files) is still running; this section will be wrong if that
comes back red, and says so rather than waiting to look finished.

### What Batch 1 got right, measured

| Item | Measured how | Verdict |
|---|---|---|
| The kill switch now actually stops orders | The send path is skipped, not merely reported: the summary is built before the send block and, when the stop file is present, the send call is never reached. The durable slot row carries the status and the reason, so a refused send can be read afterwards | WIRED |
| The reconcile halt reaches new entries only | A recorded FAIL replaces the book's breaker with a halt-only breaker after the seeding step, so the halt wins over whatever the book carried. Closes are untouched | WIRED |
| The two reader flaws | A file that exists but carries no positions key now refuses instead of answering empty, and a non-object row refuses instead of being dropped. Both were mine | FIXED |
| The breaker no longer pretends | On the real live book it returns unarmed with the reason, instead of claiming the account constant is a measured mark | FIXED |

The question I set out to answer — whether an unarmed breaker seeded from a book full of zeroes
would refuse tomorrow's entries — is answered no. Measured on the real book: the breaker is left
absent, the instant opens, entries are allowed. There is no halt risk from this change.

### Three things I found that Batch 1 did not fix

1. The reason is computed and thrown away. The seeding call returns a state dictionary that says
   armed or not and why. Nothing reads it. The slot then runs with no circuit breaker at all and
   the durable row for that slot says nothing about it. The function's own description promises an
   unarmed breaker that says why; the caller keeps the unarmed half and discards the why. This is
   the same family as every other defect closed today, one layer further out.

2. The four-percent daily-loss arm cannot fire on this route, at any equity. Every slot is a fresh
   process, so the book always opens with no current day, and opening the instant re-bases the
   day's starting equity to the equity as it stands right now. Measured: a book seeded with a
   start of 54,000 and an equity of 51,000 — a 5.6 percent day, past the limit — reports a daily
   loss of exactly 0.00 percent, because the start was overwritten with 51,000 the moment the
   instant opened. Swept five equities from 52,000 down to 41,000 against a peak of 55,000: the
   daily figure stays 0.00 in all five.

   The peak-drawdown arm does work. Same sweep: warn at about 11 percent and half size, refuse at
   about 15 percent. So one of the breaker's two arms is live and one is structurally dead, and
   nothing in the record distinguishes them.

3. The kill-switch gate pins the helper, not the wiring. It asserts what the summary function
   returns. It never asserts that the slot skips the send. Delete the one line that makes the send
   conditional and all ten tests stay green. The wiring is in fact present — I read it — but it is
   unpinned, which is the exact shape of the thing we wrote a rule about after a safety mechanism
   turned out to have code, a runbook and a grep, and no call site.

### What this means for the operator

Nothing here is a reason to hold entries. The change is safe in the direction that matters: it
removed a decorative breaker and put an honest absence in its place. What it did not do is make
the absence visible, or notice that half the breaker was never reachable in the first place.

Those two go together: as long as the daily arm is dead, an armed breaker on this route means one
thing only — a peak drawdown limit. Calling it a circuit breaker in the record overstates it.

---

## J. A5 Part 3, checked — 2026-09-25 late evening

I had this listed as "the proposal is in the report; I have not read or checked it yet". I have now
read it and checked its evidence against the files myself.

The proposed date holds. The MES row's own fill record — matched by the order id the row carries,
not by its trade id — says the entry day was 2026-09-25, and the journal's own event time, 15:07:02
ET, falls on that same ET day. The recorded entry price and the filled average price agree to the
cent. The clock stays at 15:00, which is the bar the 15:05 slot decided on, and the journal's event
time is deliberately NOT used as the value: it is when the journal wrote, not when the strategy
entered.

What repairing it changes operationally: nothing for this position. An already-placed stop is never
cancelled when a row becomes deferred, and the arm time this date implies — Saturday 14:00 ET —
falls before the Sunday evening sweep, so the first job that looks at MES afterwards sees it due,
exactly as it does now. Only the record becomes true. That makes this safe to run in the closed
weekend window rather than something to wait on.

The script is written and refuses rather than repairing blind. It checks four things independently:
exactly one open MES row, a bare clock still in place, exactly one filled journal record for that
order id, and the recorded price matching the filled price. It also refuses if the journal's own
two sources disagree about which ET day the fill fell on, rather than picking a winner.

I proved the guards can refuse rather than assuming they would. Five mutations on a copy, each one
refused with the reason naming what disagreed, and the unmutated copy still passing: a price that
disagrees with the fill, a row already dated, a missing order id, an order id pointing at no fill,
and a second open row for the same instrument.

It has not been applied. It is one command with a dry run by default, and the dry run above shows
the value it would write.

### One correction to my own earlier note

I wrote "four positions, four working stops" earlier today. That was the broker side. The book
itself records the stop LEVEL for all four rows — under a differently named field than the one I
first probed, which is why a first pass of mine read as though there were none — but no row carries
the id of the order protecting it. The link between a position and its working stop is made by
instrument at the broker, not by an id in the book. Batch 2 reconciles exactly that way, so this is
consistent rather than broken; it is worth writing down because a reader of the book alone cannot
tell which order protects which row.

---

## K. Prompts in hand — 2026-09-25, end of the ET day

Two written, neither sent. They touch disjoint files on purpose, so they can run at the same time
without colliding: one is the live slot and the signal layer, the other is dashboard and monitor only.

| File | What | Holds on |
|---|---|---|
| CODEX_TASK_RISKWIRE_BATCH1_CORRECTION_2026-09-25.md | The discarded breaker reason, the unpinned kill-switch call site, and a report-only section on the dead daily-loss arm | The wide regression count, which one of its gates needs. Nothing else |
| CODEX_TASK_PAPER_TAB_CORRECTION_2026-09-25.md | The empty-book clause I left out of my own gate, plus the two suites Batch 2 never ran | Nothing |

The second one asks for the red set BEFORE any change, because the defect description in it comes
from one suite I ran, not from reading every panel. If what it finds disagrees, the disagreement is
the finding.

---

## L. The wide regression landed — 203 red, and why that is not Batch 1

Section I said it would be wrong if this came back red. It came back red, so here is the correction.

    203 failed, 1986 passed, 5 skipped, 42m11s
    every test file under global_index, monitor and scratch importing either changed module
    finished 2026-09-25 22:18 machine time

Saved at the repo root as REGRESSION_BASELINE_2026-09-25.txt with the sorted list of failing tests
beside it, so the next change has a set to compare against rather than a count.

### Where they are

202 of the 203 are in scratch. Exactly one is in a production test directory.

That one: the dashboard truthfulness test for a naked position adding a next-protection line
asserts the protection time reads as a bare clock, and the panel now renders a weekday in front of
it. A stale string, from the dashboard round, not from Batch 1. It is written into the paper tab
prompt with the instruction to decide which side is right before changing either.

### Why the other 202 are not Batch 1 damage

Attributed by mechanism, not by a before-and-after count — and the distinction matters, so say it
plainly: I did not run this list before Batch 1, so I cannot offer two counts. What I can offer is
what each failure asserts, which is stronger for this particular family.

The scratch directory holds dated stage-gate snapshots from August, written while this route was
shadow-only. I read six of them. They fail because:

    the go-live confirmation file exists          - it was created on purpose
    the orders directory exists                   - the route sent orders on purpose
    the blocker list is down to one entry         - the others were released on purpose
    the live book is not flat                     - it holds four positions on purpose
    the executor is imported by something         - paper sending was wired on purpose
    the default route book path exists            - the route has a book now

Every one of those assertions reads live repository state. One of these files even hardcodes the
repository root as an absolute path. So their verdict is a function of what is on disk today, not of
the working tree's code — which is exactly why Batch 1 cannot be their cause, and also why a
worktree baseline at an older commit would produce the same 203 and settle nothing.

A keyword scan over the 187 failure blocks the report separates cleanly puts 115 in that family
explicitly and finds exactly one block mentioning any identifier from the changed code. I read that
one: it asserts the default route book path does not exist. It exists. Same family.

### What is still unproven

That all 202 are of that family. I read six and classified the rest by what they mention. The
remaining ones carry names of the same kind — the schedule is still sixty jobs, the journal is wired
into nothing that runs, the live book exists and is flat — but a name is not a measurement, and this
row stays at cannot-tell rather than being promoted.

What would settle it: nothing cheap. These tests do not read the working tree, so there is no
earlier tree to run them against. The honest resolution is the one already in place — the failing
SET is frozen as a baseline, and the next change is judged on whether that set changes, which does
not require knowing why any member of it is there.

---

## M. Paper tab phase 1 came back and withdrew my premise — 2026-09-26

I sent a prompt whose main item was already fixed. The report said so, and it was right. Recorded
here because the mechanism that produced the mistake will produce it again if it is not named.

### What I claimed and what is true

I claimed: zero persisted positions plus an unreadable broker renders UNKNOWN, and should render zero
of zero. That was true when section H was written. It is not true on this tree — the Batch 2 work
closed it after I wrote it down, and I re-read my own note instead of re-measuring the code.

Verified at three layers, by me:

- Backend, on a built empty-position fixture: the protection item is MISSING with the evidence line
  reading zero of zero. Not UNKNOWN.
- Front end: one function now decides the protection read for all three panels, and it tests the
  position count for zero BEFORE consulting the source status. An empty book returns a neutral tone
  and the sentence about there being nothing to protect. That is the clause I said was missing,
  ordering included.
- The paper DOM suite: 11 passed, run by me, 106 seconds.

The fix is better than the one I asked for, because three panels that disagreed were replaced by one
function rather than three corrected copies.

### The mechanism to name

A finding written down at the moment it is found becomes a claim about the past. Re-sending it later
as an instruction turns it into a claim about the present without any new measurement. Section H said
the test was still red; my own later run said eleven passed; I carried the older sentence forward
into a prompt without noticing the two disagreed.

The cost was small only because the report was asked to measure the red set before changing anything,
which is the gate that caught it. That two-phase shape has now paid for itself twice in two days.

### The one thing that was genuinely missing

The fix covers four combinations and the suite pins three. The fourth — zero positions AND a source
status of UNKNOWN together — is the one that decides the ordering inside the new function, and
nothing fails today if the two branches are swapped back. That is now a required gate with its
mutation.

### The three backend failures — all three checked by me, all stale, none hiding a defect

| Test | Verdict | What I checked rather than assumed |
|---|---|---|
| The durable-artifacts test expecting an observed protection | Stale expectation | Whether UNKNOWN swallows a recorded stop order id and loses the difference between a position with a recorded stop and one with nothing. It does not: measured on both fixtures, the id travels beside the status in two places while the status stays UNKNOWN for both. Nothing was collapsed |
| The C1 detail test expecting the old phrase | Stale expectation | That the relabel was deliberate and complete. The status code and the stylesheet class kept their names, which is why the sibling assertions still pass; only the human-facing sentence moved from cost words to correspondence words |
| The cache test whose counting stub lost a signature | Stale test double, and worse than the other two | Whether the missing route argument hid a cache-key collision, which would let one route return another route's parsed result. It does not: the key already carries the route beside the epoch, path, size and modification time. Production is correct, the stub is behind |

The third one deserves its own line. It is not asserting the wrong thing — it is asserting nothing
at all, because the stub raises before the cache is ever reached. So a caching test has been passing
as a no-op for an unknown number of runs. Repairing the signature is not the deliverable; the
deliverable is showing it go red when the memoisation is removed. If it cannot be made to fail that
way, it was never testing the cache.

That is the same family as the kill-switch gate in the other batch: a test that cannot fail has
measured nothing, and the only way to know is to make it fail on purpose.

### Sent

CODEX_PAPER_TAB_PHASE2_APPROVED_2026-09-26.md — phase 2, approved, with the withdrawal at the top so
nobody hunts a closed defect. Six gates, two of which require a red run first.

---

## N. The two rounds were not disjoint after all — 2026-09-26

I said last turn that the two prompts touch disjoint files on purpose. That was true of production
files and wrong about tests, which is the half that mattered.

Measured overlap, two of them:

The dashboard truthfulness suite imports one of the two modules the risk-wiring batch is changing, so
it sits inside that batch frozen regression set — and the weekday-prefix test failing inside it is the
ONLY member of that 203-test set outside the scratch directory. Had the paper round fixed it while the
other batch was in flight, that batch after-run would return 202, differ from its baseline, and its own
instructions would make it stop and report a difference. A false alarm costing a forty-minute run.

Second: that suite drives a browser in sixty-nine places and the paper DOM suite drives one too. Two
browser suites at once on this machine is a trap already recorded here.

The two suites the paper round actually needs — the backend suite and the paper DOM suite — are not in
the other batch list. Checked, not assumed.

Resolution: the weekday item is pulled out of the paper round into its own later round, an explicit
gate forbids running or touching anything in the other batch set, and the paper round waits until the
risk-wiring batch lands. Serialising costs less than one false stop.

The thing to carry forward: file-level disjointness is not batch-level disjointness. Two rounds can
own separate production files and still collide through a test that imports one of them, or through a
frozen baseline that one of them is a member of. The check is not "do they edit the same file" but
"can one change what the other measures".

---

## O. The frozen baseline was a bad gate, and the report that stopped on it was right — 2026-09-26

The risk-wiring round ran its before-run, got 201 failing where my frozen set had 203, and stopped
exactly as instructed. Both missing members had gone GREEN. No new red anywhere.

I chased both rather than waving them through.

The first reads the LIVE scheduler process and skips when the process query returns empty. Measured:
the scheduler never stopped, it is the same process from 2026-09-25 06:01, and its command line does
carry the arming flag — so the test FAILS whenever it can actually see the argv, which it does when I
run it alone. Inside a thirty-seven-minute fully loaded run the query came back empty and it skipped,
which is exactly the extra skip in that run totals. A test that skips under load is not a fixed point.

The second is a browser test that passes run by itself and failed inside my forty-two-minute run. Same
tree, different load. Mechanism not proven; the signature is load, not code, and it stays at that
label rather than being promoted.

So the fault was mine, and it is worth naming precisely: I built a no-regression gate on a basis that
is not a function of the tree. Most of that scratch directory asserts things about live processes and
live files, not about code. Freezing their verdicts and demanding reproduction guarantees a false
stop as soon as the machine is busy.

### What replaced it

Blocking part: only the production suites from the list, ten files under global_index and monitor.
Measured 2026-09-26: 1 failed, 133 passed, thirty seconds. The one failure is the weekday-prefix
string that belongs to the dashboard round. Deterministic, and it is where a regression in the changed
modules would actually show.

Informational part: the scratch portion, reported but not blocking.

Ten times faster and it actually measures the thing it claims to.

### What the thirty-second run caught immediately

The golden that pins every on-disk position row went red — because the operator had just applied the
MES date repair, which is precisely the change the V2 report predicted would move it, with the
instruction to update that line at that moment and not before. This was that moment.

The gate behaved perfectly: its digest check confirmed every other loaded value on that row was
byte-identical, and the only difference was the one intended date. I added MES to the permitted list
with the reason, and proved the gate still bites in both directions — a copy that drops MES back off
the list goes red, and a copy that demands a change which did not happen also goes red, while the real
one is green. Nine of nine.

Had I skipped the fast production run because the slow one had already finished, this would have sat
red until something else tripped over it.

---

## P. Risk-wiring correction, Part A — verified by me; Part B never arrived — 2026-09-26

The round reported Part A complete and listed two changed files. It showed none of the five gates, no
red run, no regression number, and not one line of Part B. So everything below is my measurement.

### Part A1 — the breaker reason now reaches the record. WIRED.

The slot no longer throws the state away. It carries three fields into the durable row and the same
dictionary into the returned payload. Both states, measured on real slot runs:

    armed    breaker_armed=true   reason=null
    unarmed  breaker_armed=false  reason="route book carries no non-zero measured equity/peak"

Both rows also read decided=true with one candidate accepted, which is the over-application half: an
armed slot behaves exactly as before and the fields are additive.

Worth noting what the shape gets right without being asked. The armed flag is null — not false —
when the seeding step never ran at all, so the row distinguishes armed from unarmed from never-asked.
Three states, kept apart.

### Part A2 — the call site. WIRED, but the gate for it reads source text, not behaviour.

The gate added takes the slot source and asserts three lines appear in order. It does catch the
mutation I named, because deleting the conditional makes its index lookup raise. It cannot catch a
conditional that is present, correctly placed, and no longer governs the send.

So I proved the behaviour instead of trusting the text. Ran the real slot twice with a spy standing
in for the send:

    no stop file  -> the send IS reached, one decision
    stop file     -> the send is reached ZERO times, and the row records gate_closed naming the file

The control is the load-bearing half: without it, "not reached" is satisfied by a harness that never
reaches the send under any conditions.

That proof is now a permanent suite of its own rather than something I ran once, and I falsified it
rather than assuming: neutralising the switch so the summary is always absent makes the send reachable
again with the stop file still in place, and the gate goes red. A third test pins that a gated slot
still records what it saw — refusing to send is not refusing to observe.

### The blocking regression gate

    1 failed, 138 passed, 26 seconds

The one failure is the weekday-prefix string that belongs to the dashboard round. Baseline was 133
passing; the arithmetic closes as 133 + 2 from the correction + 3 from my behavioural suite. No
regression.

### Not delivered

Part B. Nothing was reported on the daily-loss arm — not the re-base, not the absence of any component
that writes an equity mark, not where the record overstates what the breaker is. That was the section
that feeds an operator decision, and it is the one still missing. It remains report-only: no code.

---

## Q. Dashboard Phase 2 — the seven unmeasured items, now measured — 2026-09-26

Section H left ten items reported complete with three confirmed and seven plus every suite count at
claimed-but-not-measured. That label is now closed. Nothing here is taken from the report that made
the changes.

### Suite counts, collected and run by me

    realtime DOM                 88 collected, 88 passed
    realtime contract            27 collected
    job row never invents a cause 5 collected, and it RUNS -- the module skip is gone
    paper DOM                    11 collected, 11 passed
    dashboard truthfulness       20 collected, 19 passed, 1 failed
    dashboard backend           225 collected

The eighty-eight matters: one gate named that exact number as a figure that must not move, and it has
not. The three suites together ran 120 green in 3m53s.

The backend suite total of 225 is the collected count; three of them are red today and they are the
stale fixtures the paper round is approved to fix, which is how 222 plus 3 gets back to 225.

### The two backend items, read rather than run

Item 1 is present AND carries the constraint I added rather than only the version proposed. The
journal-to-jobs helper refuses outright when the journal day does not equal the day asked for, so a
repeated job id cannot attach yesterday reason. It is read once and indexed, and the distinct
no-record status exists.

Item 4 is present and matches on the FULL trade id, which carries the date inside it, so a candidate
for the same instrument on another date cannot match a fill. The execution fact is a separate
structured field naming its own source, not a rewrite of the decision reason.

### The five front-end items

Every gate from G8.1 to G12.4 has a test named for it -- fourteen of them -- including all four
over-application guards and the four-case matrix that puts a position on each side of its own arming
time for both sleeves. Thirteen of the fourteen are green.

The fourteenth is the weekday-prefix failure already known. Worth stating precisely, because it would
be easy to read that red as the item failing: inside that same test, the assertion that a next
protection line appears passes, and the assertion that it does not displace the next job passes. Only
the assertion that the time reads as a bare clock fails, because the panel now prints a weekday in
front of it. The item works; one string in its test is behind the renderer.

### Label change

Items 1, 4, 6, 7, 8, 9 and 10, and every suite count: moved from claimed-but-not-measured to verified.
The one open thread is the weekday string, already written into the paper round successor.

---

## R. Paper tab phase 2 — it stopped at the right gate, and that gate had a real answer — 2026-09-26

The round did the required work, then stopped at the cache gate rather than repairing a test it could
not make fail. That was the correct call and the answer underneath it is worth more than the fix would
have been.

### What it delivered, verified by me

Two of the three stale fixtures are fixed: the backend suite went from 3 failing to 1. The fourth
combination is pinned -- no positions AND a source reporting unknown, folded into the existing
empty-book test rather than bolted on beside it, which is the better shape. Paper DOM still 11 green.
Scope held: nothing under scratch, nothing in the dashboard truthfulness suite, which is the other
batch regression member.

### The cache gate — answered, and the answer is that the test could never fail

The stale stub signature was the smaller half. The test detected a re-read by asking whether the cache
had GAINED an entry. After the warm-up it never gains one. Measured with the signature repaired and
the scan entered seventy-four times in both runs:

    with the cache      detector reported nothing
    cache neutralised   detector reported nothing, and every file was parsed again

So repairing it would have produced a test that passes in both worlds — occupying the place where a
real one belongs. It is REMOVED, not repaired, with the measurement written where it stood.

The replacement counts the read that actually costs: a warm second pass must read zero log files from
disk. Measured: zero with the memoisation, and with it neutralised the read count rises to exactly the
number of scans. Both directions are tests in the file, so its ability to fail cannot rot away.

### The branch-ordering gate, also closed by me

The DOM suite pins the four answers but cannot show that the ORDER of two branches is what produces
one of them. So the function is lifted out of the page and run directly, then run again with those two
branches swapped. Measured:

    as shipped        no positions, no broker -> neutral, 0/0
    branches swapped  no positions, no broker -> watch, unknown

The defect returns under the swap, and nothing else moves — a position with an unreadable broker reads
unknown either way. So the ordering is load-bearing and now says so. No file was modified; the mutation
lives inside one browser evaluation.

### Counts

    dashboard backend                     224 passed, 0 failed
    paper DOM                              11 passed
    log cache counts real reads (new)       2 passed
    protection read order (new)             2 passed
    dashboard truthfulness             19 passed, 1 failed -- the weekday string, untouched on purpose

The target was 225 passing with none failing. It landed as 224 plus 4 across two new files, with a
tautology deleted rather than counted.

---

## S. Part B answered, and the writer it says does not exist DOES exist — one route over — 2026-09-26

The report is sound and it added a control I had not thought of: pre-seed the day start and DO NOT let
the open rebase it, and the daily arm fires properly -- HALT_DAY at 5.56 percent. So the branch is not
fictional. It is unreachable, which is a different and more fixable thing.

Two rebase paths exist, and between us we found one each. The update call initialises the day start
only when it is absent; the day-open call overwrites it unconditionally. The one that kills a seeded
value on the live route is the second, which is the one I measured. The report measured the first.
Both are true and together they close the question: there is no path through a fresh slot on which a
seeded day start survives to be compared against.

### A correction to my own number

I told the operator the drawdown arm warns "around 11 percent" and halts "around 15". Those were the
lowest values I happened to sample in each band, not the thresholds. The report said 12.73 for the same
reason. Read from the code: warn at exactly 10 percent, halt at exactly 15, daily at exactly 4. Neither
of us had pinned the threshold, only bracketed it.

### One of the six naming places is not a naming problem

Five are wording. The sixth is a justification resting on a rule that does not run. A note in the paper
inputs argues for a two-thousand-dollar daily figure like this: the existing runtime circuit breaker
halts at minus four percent of a fifty-thousand sleeve, the twenty-session floor lands within
seventy-three dollars of one such trip, and two rules built independently arriving at the same size is
a sign the size matches the risk appetite already wired into the system.

The minus-four-percent arm cannot fire on this route. And the two-thousand figure it corroborates is
DISPLAYED ONLY -- measured: it appears in a data file, is rendered on the paper tab, and no Python
reads it. So two numbers that nothing enforces are presented as independent confirmation of each other.

Being fair to whoever wrote it: on the route it was written about, the arm probably did fire. What went
wrong is that the trading moved to a route where it cannot, and the note was never re-checked.

### The finding that changes the decision

The report says no component writes a true equity mark, and on THIS route that is correct. But the
writer exists. The legacy route book, read just now, carries a full breaker block with real numbers:
a peak, a day start, a session day, a system equity of 50,408.25 and, separately, a last broker equity
of 996,730.93.

And the code that writes it states the reason in its own words: every cron slot is a separate process,
so the system ledger and the broker mark it was reconciled against must both survive on disk, or equity
resets to base each slot and the same profit is re-booked every five minutes.

That is Track 1 problem, solved, one route over, years before Track 1 had it. Legacy also solved the
trap underneath it -- it keeps the sleeve equity and the whole account balance as two separate fields,
and carries a guard that DISCARDS a persisted peak larger than five times the account base, with a log
line explaining that such a value was recorded against the broker balance rather than the system base.
That guard exists because someone once wrote 995,000 where 50,000 belonged.

So this is not a design decision about which equity source to invent. Track 1 reshaped the schema --
those fields moved out of a nested breaker block to the top level, schema version one to two -- and the
writer was not carried across. The question for the operator shrinks to: port it, and which legacy
field maps to which Track 1 field.

Worth noting the reader on the new route already behaves correctly for the port: it treats the zeros as
absent and says so rather than trusting them, so the day a writer starts filling them the breaker arms
itself with no further change.

---

## T. Legacy comes off the dashboard — survey commissioned, and the one thing that must not go with it

Operator decision, 2026-09-26. Phase 1 is a survey because the surface is about four hundred references
and three of them are load-bearing for something unrelated to legacy.

The measurement that makes removal safe rather than blinding: the legacy book holds ZERO open positions.
The drain is finished. There is nothing left on that route for a panel to fail to show.

Three carve-outs written into the task:

The legacy book is the only place a working equity mark exists, and its writer is the model for the port
Track 1 needs. Legacy comes off the DASHBOARD; its equity bookkeeping stays until that port happens.
A removal that touches it is to be listed, not proposed.

The slot table names legacy sixty-six times and most are a parity check that uses the legacy schedule as
a yardstick for Track 1 correctness. Removing the yardstick deletes the check.

The eighty-one references in the ops module are operations, not dashboard. Out of scope entirely.

Two consequences flagged as operator decisions rather than work: the staleness dimming mechanism and its
four gates protect nothing once legacy leaves the page, and eleven registered legacy safety jobs now
guard zero positions while a test pins the total job count.

---

## U. The weekday string, closed by me — and the gate is green for the first time — 2026-09-26

I had queued this as its own round and it did not deserve one, because the question of which side was
right was already answerable: ALL THREE rows of that bar render a weekday, and the test asserted a bare
clock on one of them. The renderer is right and the line was behind it. A protection job shown as
16:20 ET alone cannot be told from the same job tomorrow, which is precisely what an operator reading
that row is asking.

So the assertion now carries the weekday rather than having it stripped out, and a second assertion was
added on the next-job row, so a renderer that drops the weekday again fails instead of passing quietly.

    dashboard truthfulness    20 passed, 0 failed
    the blocking gate        139 passed, 0 failed

That gate has carried one known red all day. It is green.

## V. Two rounds commissioned in parallel, and they cannot collide

Both are surveys. Neither writes a file, so the usual question of overlapping scope does not arise at
all — which is the first time today that has been true.

    legacy off the dashboard     classify about four hundred references into four buckets
    the equity writer port       design the port the breaker needs, six questions

They read the same legacy bookkeeping from opposite directions on purpose. The dashboard survey is told
that bookkeeping stays until the port exists; the port survey is told to read legacy as much as it likes
and change nothing. If either comes back proposing to move it, the other one is the reason not to.

The port survey carries the finding that reframes it: this is a port, not an invention. The question of
which equity source is authoritative was answered years ago by the route that ran — the sleeve own
system equity, with the broker mark kept beside it and never allowed to flow into it — and the guard
against confusing the two already exists because the confusion already happened.

---

## W. The legacy survey — accurate on 308 of 309, and the one it got wrong would have stripped live protection

Counts check out exactly. My own count of the in-scope surface was 309 and so was the survey; the four
buckets sum to 309. I sampled the KEEP reasoning in the realtime page and it is right, including the
part that matters most.

### The headline the survey establishes

Only 43 of 309 references are actually removals. Eighty-six percent of the legacy mentions on this page
exist to stop Track 1 facts being filled with legacy values, or to label a fallback honestly as
legacy. Taking legacy off the dashboard is, mostly, not a removal job. Sampled and confirmed: a long
run of those comments record a panel that USED to read the legacy runner and now reads Track 1, keeping
the legacy reading only as a fallback that says whose it is.

### The one that is wrong, and it is the dangerous kind

The survey reports eleven legacy safety jobs still registered and computes the schedule going from 93
slots to 82 if they are turned off. Acting on that would remove the stop-repair sweeps and the max-hold
exit that protect the four live positions.

There are TWO different elevens in this system and they coincide by accident.

Legacy had eleven safety sweeps. They came off the schedule on 2026-09-06, in a commit whose message
says so and gives the reason: the book had held nothing since 2026-09-04. That matches what I measured
today — zero open positions on that route.

Track 1 has its own eleven safety jobs, and every one of them is named for Track 1: the max-hold exit,
nine stop repairs, and the Sunday sweep. Those are live. The Sunday sweep is the next scheduled job on
the machine.

What the survey actually counted was neither: a slot constant in the schedule reader with no route in
its name, generating every even hour at twenty past except two and fourteen. Ten slots plus Sunday is
eleven. Its membership gives it away — it contains 12:20, which Track 1 does not have, because Track 1
skips the hours inside its own Stress window.

So: a constant with no route in its name, a count that happens to equal the live route own, and a
conclusion that those eleven are the retired route and removable. Nothing in the schedule needs to
change; the change was made three weeks ago.

### An ordering defect inside the proposal

The REMOVE bucket includes the backend serving of the legacy payload, described as existing only to
feed a legacy display. The DECIDE bucket leaves the page fallback mechanics undecided. But the page
reads that payload by name, deliberately, so that the legacy figure is labelled legacy instead of
Track 1 measured equity being captioned as the legacy runner state.

Remove the producer while the consumer decision is still open and the panel reads an absent value. That
is the failure family this entire day has been about. The producer cannot go first.

### The fork the operator actually has to settle

Not four hundred references. One question: does an honestly-labelled fallback to a retired route earn
its place on the page.

With legacy holding nothing and no longer trading, that fallback can only ever show a figure from a
route that stopped. The page already has the vocabulary for absence — it spent today learning to say
not-recorded instead of zero, and unknown instead of missing. My recommendation is that the fallbacks
become explicit absence, which turns most of the sixty-eight undecided references into removals and
lets the backend producer go in the same change rather than before it.

---

## X. The equity-writer design — sound, and two things it does not cover

The report answers all six questions, states the crux correctly, and says the thing that matters most
without being asked: arming a dead safety layer changes which entries are admitted. It is not a
reporting change. That sentence is the reason this is a phase and not a patch.

Its mapping is right and its answer to the crux is right — seed the session day alongside the equity
fields, and make the day-open step treat a session day equal to today as a day already open. The book
already carries that field. Two things it does not cover, both measured.

### The guard it proposes only bounds the harmless direction

It ports the legacy trap guard: refuse a persisted value larger than five times the account base.
Measured against a day start of that shape, with equity at 48,000:

    correct           50,408.25   daily   4.78%   halts       passes the guard
    broker balance   996,730.93   daily  95.18%   halts       REFUSED by the guard
    a P&L delta         408.25     daily -11657%   DOES NOT    passes the guard
    zero (today)          0.00     daily   0.00%   DOES NOT    passes the guard

The direction the guard catches is the one that fails safe on its own: a value far too large makes the
breaker halt spuriously, which is annoying and visible. The direction it misses is the one that
silently disarms — a value far too small makes the daily arm unreachable again, reporting a daily loss
of minus eleven thousand percent and admitting every entry.

And zero is simply the extreme of too-small, which is exactly what the live book carries today. So the
guard as proposed would pass the current broken state without comment.

What it needs is a plausibility BAND rather than an upper bound. A band also subsumes the reader current
zero check and makes it principled instead of a special case: one rule saying what an equity mark is
allowed to look like, rather than one rule for absurdly large and another for exactly zero.

Same family as a symmetric measure that cannot see risk: a guard whose only bound is on the side that
protects itself.

### The question that has no answer yet: two sessions share one day field

Measured slot hours: the Tokyo sleeve runs 01:10 to 02:55 ET; the afternoon sleeve runs 14:05 to 15:55
ET. Same ET calendar day, thirteen hours apart, one shared session-day field and one shared day start.

So the first slot of the day is a night slot. It opens the day and sets the baseline. The afternoon
sleeve then measures its daily loss against a mark taken thirteen hours earlier that already contains
the whole overnight session. The afternoon can be refused entry on a day it has not traded, because the
night lost four percent — and the reverse, a night gain hands the afternoon a cushion it did not earn.

Legacy never met this, because legacy had only ET-hours sleeves and one calendar day WAS one session.
The port therefore inherits a design that was never tested against a route carrying a Tokyo-hours sleeve.

Three ways out, and this is the operator to choose, not the implementer:

    one baseline per ET day, shared        account-level risk; the night can close the afternoon
    a baseline per sleeve                  each session measured against its own open
    one baseline reset at a chosen instant  for example before the afternoon window opens

Which one matches the validated model is a question about the backtest, not about this code, and it has
to be answered before the port lands, because all three admit different entries.

---

## Y. What the backtest actually validated — and a fork that supersedes the one I asked about

The read-only round answered both questions well. I verified its two load-bearing claims myself and
one of them led somewhere more serious than the question I asked.

### Question 1 — answered, and then replaced by a sharper one

The shared-baseline question is settled: the accepted portfolio replay keeps ONE equity, ONE breaker
and ONE session day, and every cluster P&L lands on the same equity. The situation I worried might
never have arisen in the model arose 37 times — 37 afternoon trades sit on a day key that also carries
a Nikkei trade. So a shared daily baseline is what was validated, and the live design should follow it.

One nuance worth keeping: the day key drops the timezone and normalises, so it is each trade own
LOCAL date, not a common ET date. Tokyo 15:00 and New York 15:50 on the same nominal date collapse to
one key. Live does the same thing, so they match — but the rule is not "one ET day", it is "one naive
date per timestamp as handed in", and anything that changes what timezone a caller passes changes the
grouping.

### The fork that replaces it, and it lands on the arm we are about to switch on

The accepted producer resets the day baseline BEFORE booking that instant closes. Live does the
reverse: it settles first, then re-bases.

This is not a subtle inference. The legacy decision path states the consequence in its own comment,
in its own words: the baseline it captures already includes the day first exits, so a loss realised in
the first call of a day sets that day baseline below itself and CAN NEVER TRIP the day halt from
there. It goes on to name what falls outside — the first batch, which is also the largest: the 14:05
signal exits and anything the max-hold job closed at 09:31.

So the live four-percent brake measures from AFTER the day largest closes. The replay that produced the
accepted figures measures from before them. Live is the structurally weaker version and the repository
documented that without anyone connecting it to the accepted model.

And the comment on the live day-open makes a claim that does not survive this. It says the ordering is
the one every measured Track 1 figure was produced under. Two claims are packed into that: that live
matches the legacy decision path, which is TRUE, and that the legacy decision path produced the
accepted figures, which is FALSE. The error is the word therefore.

This has to be settled BEFORE the equity writer lands, or the daily arm fires for the first time on a
rule nobody validated. It is a genuine operator fork: match the accepted replay and count the day
opening closes, or keep the live ordering and accept a weaker brake on purpose and say so where it is
described.

### Question 2 — fixed capital confirmed, and the real defect is not the wording

Fixed contract counts, fixed fifty-thousand denominator, equity feeding the breaker and metrics but
never flowing back into quantity. Live matches the accepted model on this. The one soft spot is that
the same figure is declared twice in two places rather than shared from one.

Then the part that matters. The page and the admission gate both say gross exposure and they are not
the same quantity, in either half of the fraction:

    the gate   max(long risk, short risk) / fixed 50,000    measured today: 7.63%
    the page   sum of position notional / booked equity

Measured on the live book: no position row carries a notional or market-value field at all, so the page
sum is zero and it renders a held count instead of a percentage. Today that is honest — a branch above
catches the missing curve and says the route has booked no equity to express positions against.

I predicted an infinity on that division and I was wrong; the guard is one branch up and I had read the
division line alone. The measurement corrected it.

But the port makes that branch reachable. Once equity is written, the code enters the division and
still finds nothing to sum, so it renders a count under a title claiming it is expressed against booked
equity — wrong in a new way. And if anyone ever populates the missing field, the page would show
contract value over account, which is orders of magnitude above the gate 7.63 percent, under the same
word.

So A9 is not a caption fix. The page gross has never worked, its input field does not exist, and it is
a different quantity from the one the cap enforces. The decision is which of the two the page should
show, and only then what to call it.

---

## Z. The plausibility band — clean, and my objection to it did not survive reading it

Re-measured by me: seven suites, 79 passed, matching the count reported. The band derives from the
account on the book rather than a literal, the broker mark is left out of the checked set, and the
out-of-band reason names the offending field, its value, the band and the account the band came from —
more than I asked for. Two reasons stay distinct: no measured marks at all, versus a mark present and
out of band. Those were the same sentence before today.

### I came to this with an objection and it was wrong

I was going to argue that the lower edge is too generous — that a mark at a fifth of the account base
implies a drawdown the sleeve position sizing cannot produce, and that the tolerances should be
asymmetric because an error downward disarms while an error upward halts spuriously.

The code answers it in its own comment before I got there: even the lower edge is far beyond every
breaker threshold, so this validates the UNIT and IDENTITY of a mark without touching the 10 / 15 / 4
policy. That is a narrower job than the one I was about to judge it against, and for that job a factor
of five each way is right. Tightening the lower bound toward what the sizing can actually lose would
push risk policy into a unit check, which is the category error, not the fix.

Agreeing is also a conclusion and has to be measured. The measurement here was reading the sentence
that states the purpose.

### What remains after it, and it is not a criticism of it

A unit check cannot catch a wrong value in the right unit. Yesterday equity, another sleeve equity, a
mark that stopped advancing — all in band, all dollar-denominated, all silently armed. That is outside
this change stated scope and it is the gap that remains: when the writer lands, the breaker must not be
considered guarded because this band exists. It is guarded against the wrong KIND of number, not the
wrong number.

### One corner the writer round should decide

Equity and peak are required; the day start is optional and falls back to current equity when absent.
Today that is the honest reading — a book that never recorded a day start has not opened a day, so now
is the only defensible baseline, and unlike the rebase bug this fills an absent value rather than
destroying a recorded one.

But once a writer always writes it, an absent day start becomes surprising, and this is the one path
that can produce a breaker which looks armed while its daily arm measures from this instant and
therefore measures nothing. Whether that should refuse instead of filling is a decision for the writer
round, not a defect here.

---

## AA. The legacy removal took the circuit breaker display with it — 2026-09-26

STOP SIGN on this round. It must not be marked complete and its failing tests must not be rewritten to
pass. They are right.

### What the round did not report

It EDITED monitor/test_realtime_dom.py and did not run that suite in full — G5 lists three suites and
that is not one of them, only focused nodes from it. I ran it: 8 failed, 80 passed. It was 88 passed.

    test_sharpe_is_withheld_below_the_sample_floor
    test_sharpe_is_shown_once_the_sample_is_long_enough
    test_a_tripped_circuit_breaker_is_never_reported_as_nominal[HALTED]
    test_a_tripped_circuit_breaker_is_never_reported_as_nominal[SHUTDOWN]
    test_numbers_from_a_dead_source_are_not_shown_as_current
    test_a_stale_model_is_shown_as_debt_without_crying_wolf
    test_a_failed_refreeze_is_shown_as_debt_not_as_an_incident
    test_blocked_entries_are_visible_on_the_page

### The one I traced, and it is the worst kind

With a tripped breaker in the payload, the status rail reads:

    systems nominal: feeds live, no open positions

A safety layer has fired and the top line of the page says everything is fine.

Traced to the mechanism rather than guessed. The rail builds a list of things that are wrong and says
nominal when the list is empty — its own comment states that design: only add a line when the answer is
no. A page whose default is nominal cannot afford to lose a condition, and this lost one.

The breaker condition is fed by two expressions and BOTH are legacy. One reads the level out of a
helper whose argument is the legacy snapshot; the other reads the snapshot directly. And the Track 1
runtime payload carries no breaker at all — measured, the key is absent, and its safety block holds
jobs and paths while its gates block holds only whether orders are possible.

So Track 1 never published a breaker level. The page has always read it from legacy. Remove legacy and
the page has no source for it, and the default is nominal.

This is not a stale fixture. The test is correct and the change is incomplete.

### I was wrong twice on the way here and both corrections came from measurement

I thought the declaration had been deleted while its four uses remained, which would have thrown and
explained all eight failures at once. It had not — it was narrowed, not removed. And I first read the
deletion as a guard removed outright when it was a guard whose legacy half was fenced off.

Neither correction changes the verdict, and the verdict got worse rather than better: a deleted
declaration would have been loud. A source that quietly has no replacement is not.

### The collision no single round could see

Today the Track 1 breaker is UNARMED — it has no equity marks, measured this morning. So the page is
not hiding a tripped breaker right now, because nothing can trip.

The equity-writer port is about to change that. One round removed the breaker only display source while
another is preparing to give the breaker something to trip on. Neither could see the other.

So this becomes a hard ordering rule for the programme: THE EQUITY WRITER MUST NOT LAND BEFORE THE PAGE
CAN SHOW A TRIPPED BREAKER. Otherwise the first real halt on this route is invisible, and the line the
operator reads at the top of the page says systems nominal while it happens.

### What must happen

Not a revert; most of the removal is right. Track 1 has to publish its own breaker level into its
runtime payload, and the page has to read it there. Then these tests pass on the Track 1 path and the
legacy source can go. Until that exists, the removal of THESE signals is held.

The other seven failures are unexamined. One of them touches the model age, which does have a Track 1
source, so they are not all guaranteed to be the same root cause and each needs the same treatment:
trace it, then decide whether the test or the change is wrong. Not the other way round.

---

## AB. The unreadable book now refuses — the item that was open all day, and the only one with a
## measured cost, is closed

Re-measured by me, not taken from the report:

    four named suites            111 passed  (8 + 11 + 53 + 39)
    dialect suite                11, up from 10 — the new test is the only addition

The refusal names the file and the parse failure, and its test asserts the on-disk BYTES are unchanged
after the failed load rather than a row count. That was the gate I insisted on, because a row count can
match while the envelope was rewritten — which is what happened in the incident.

The red-first evidence is real and shown: before the loader change the same test reports DID NOT RAISE,
and the captured log carries the exact warning line from the incident — failed to load, fresh start,
manually verify broker has no orphaned positions. That line is now a raise.

The over-application guard holds: the golden pins 5 rows loading and 5 raising, and counts how many are
rescued as dialect cases, so a change that rescued everything would fail it.

### The check the round did not make, and the answer

Neither the report nor the proposal tried loading the two REAL books through the changed loader. That is
the question that decides whether the next scheduled slot lives: the raise sits in the runner
constructor, so a book row that now throws kills the sweep before it can place a stop.

Measured: all four live Track 1 rows load cleanly, with their instrument, contract count, risk and
cluster intact; the legacy book holds zero rows; and no live row would be dropped by the corrupt-value
filter that sits just below. The next slot does not die.

### What it costs, as accepted

A corrupt book now stops the safety sweeps: they exit non-zero and the failure is visible. The proposal
compared the two worlds and the comparison holds — no stops are placed either way, and the difference is
whether the book survives and whether anyone is told.

Still not fixed, and correctly out of scope: the scheduler drops child warning lines and the journal
classifies such a failure as unclassified. The proposal said this change makes those matter less rather
than fixing them, and that is what happened.

---

## AC. The breaker publisher landed and reports the OPPOSITE of the truth — 2026-09-26 late

The round fixed the eight failures and the suite is 90 green, up from 88 by two new tests. And the
thing it published is false.

Same file, same instant, two readers:

    signal layer  armed=False   out-of-band equity=0.0, peak_equity=0.0, day_start_equity=0.0
                  and book.breaker is None
    dashboard     armed=True    status=ARMED  level=OK  allow_new_entries=True

Before this round the page said systems nominal because it had NO source — an absence. Now it makes a
positive claim that the risk brake is armed and within limits. That is worse than what it replaced.

### The mechanism, traced, and it is not fabrication

Two links.

The honest branch is unreachable. It fires on armed is False, read from the newest durable slot row
carrying the arming fields. Those fields were added this morning and no slot has run since, because it
is Saturday. Measured: that row is None. So the branch that would say UNARMED cannot fire, and the
branch designed to be the truthful one is the least reachable one in the function.

Then zero passes as a mark. The next branch tests equity is not None and peak is not None, and 0.0 is
not None. So it builds a breaker with peak zero and day start zero, asks its status at equity zero, and
gets level OK with entries allowed — because a zero drawdown from a zero peak is zero. Hence ARMED.

### What this actually is

A SECOND copy of the reading logic, without the band. The plausibility band that refuses zeros lives in
the signal layer. The dashboard reader re-implements the same question and does not have it.

That is the defect family this entire day was spent collapsing — three panels answering the empty book
three ways, two readers of the book disagreeing about dialects, a comment asserting an ordering that
another file contradicts. Every one of those was fixed by making one place answer the question. This
round created a new second place.

### The gate that would have caught it, and none of the 90 tests is it

Not another assertion about the payload. An assertion that the TWO READERS AGREE on the same file: ask
the signal layer whether it would arm, ask the dashboard what it reports, and require them to match.

That test cannot be satisfied by two divergent copies, which is exactly why it is the one to write. Ninety
tests passed without it.

---

## AD. One breaker truth — landed and verified. And the agreement gate does not reach far enough.

Verified by me, not taken from the report. There is now ONE decision function in the signal layer; the
slot path calls it and the dashboard imports and calls the same one. On the live book both produce
armed=False with the SAME reason string, character for character, and the payload reads UNARMED instead
of ARMED / OK. The realtime suite stays at 90. The red-before evidence is real and shows the old ARMED
against the new UNARMED side by side.

The residual duplication is acceptable and worth naming so nobody mistakes it for a second copy: the
dashboard still constructs a breaker to compute a DISPLAY LEVEL once the arming decision has been made
elsewhere. The decision is shared; the level is the same class with the same thresholds.

### What the agreement gate does not cover

Its test compares two READERS OF THE BOOK. Both read the recorded day start. The running slot does not.

Measured, on a book with plausible marks — equity 51,000, peak 55,000, day start 54,000, which is a 5.6
percent day and past the four percent limit:

    the dashboard reports        ARMED, level HALT_DAY, daily 5.56%, entries refused
    the running slot holds        level OK, daily 0.00%, entries ALLOWED
                                 and its day start has been overwritten to 51,000

They disagree, and in the worse direction: the page says the brake fired and the engine lets trades
through. Today the agreement test passes only because both sides say UNARMED. The day marks exist, the
page and the engine contradict each other in public.

So the gate needs extending: compare the dashboard against the SLOT BREAKER AFTER THE DAY OPENS, not
only against the shared book reader. Two readers of the same file will always agree; that is not the
question an operator is asking.

### The third independent reason the ordering decision comes first

One: the live brake measures from after the day largest closes, which is weaker than the replay that
produced the accepted figures.
Two: a day start read from disk is destroyed by the day-open before it is ever compared against.
Three, new: once marks exist, the dashboard and the engine will visibly disagree about whether entries
are halted, and the honest one will be the page.

All three are the same root — the day-open rebase — and all three land the moment the equity writer
runs. The writer must not run before the ordering is chosen.

---

## AE. Option (a) chosen — and the choice has a cost nobody had priced

Operator decision 2026-09-26: the day baseline is taken BEFORE the day first closes are booked, matching
the replay that produced the accepted portfolio figures.

Before writing the task I measured one thing that changes its shape. The function whose ordering this
alters is the same one that produced Track 1 OWN recorded figures — a comment in the parameters module
names that function and quotes a figure difference for a vault window, so the vault runs go through it.

Which means the two number sets in this repository were produced under two different day-boundary rules:
the accepted PORTFOLIO figures under (a), and Track 1 own recorded figures under (b).

So adopting (a) can move Track 1 recorded numbers. That is not a reason to reverse the decision — (a) is
the rule with evidence behind it — but it means the change cannot simply be implemented. The task is
written with a HARD STOP: reproduce the recorded figures, apply only the ordering change, reproduce them
again, and if anything moved, stop and report. A moved figure is an operator decision about what replaces
the record, not a consequence to absorb quietly.

Also written in, because I measured it: (a) is three steps, not a swap of two lines. The day rolls and
the baseline is captured before settling; the breaker update and verdict stay after it. Doing it as a
swap would move the update ahead of the closes and the peak would miss the instant profit and loss —
the same class of bug pointed the other way.

And the trap that the easiest implementation walks into: a flag already exists that serialises all three
marks, and turning it on for a live slot writes the account constant as a measured mark, in the right
unit, inside the plausibility band. The band passes it and the breaker arms on a fabricated number. The
task forbids that path by name and requires the writer to be incapable of writing an unmeasured number.

---

## AF. The day boundary landed, the brake fires for the first time, and one number is all that is left

Re-measured by me across six suites: 62 passed. The ordering in the instant loop is the accepted three
steps and the docstring now says so — day opens, closes settle, breaker updates and rules. The false
therefore that claimed the old order produced every measured figure is gone with it.

### Stage 1 answered the question it was written for

No figure moved. Floor, vault2025 and vault2026 identical before and after. So adopting (a) does NOT
invalidate Track 1 recorded numbers, and the hard stop did not need to fire.

Worth reading correctly though: that reproduction is a guard against COLLATERAL damage and it passed. It
is not evidence the change works, because the daily arm never fired in those windows — the floor shows
two halts across its whole span and the vaults show none. The evidence that the change works is the
constructed case: 0.00 percent under the old order, 5.5556 percent and a day halt under the new one.

### The whole chain, run end to end, which nobody had done

The report proved the pieces. I ran the sequence:

    the book as it stands today       unarmed, with its reason
    one real starting value written   ARMED, all three marks read back
    a later slot the same session day baseline PRESERVED at 50,408.25 — the rebase bug is gone
    a realised loss of 2,100 booked   daily 4.17%, level HALT_DAY, entries REFUSED

That is the first time the four-percent daily arm has produced a refusal on this route.

### What is left is one number, and it needs no derivation

Measured: ZERO closed trades on the Track 1 route. Four positions open, nothing realised, the booked
counter and the counters both empty. So the route system equity is exactly the design base of fifty
thousand, and equity here is realised-only — the book adds profit and loss at settlement, which matches
the model that books at exits.

Which means the seed needs no computing. But the distinction matters and must survive into whatever
writes it:

    fifty thousand because it is the default sitting in a fresh book   -- fabrication
    fifty thousand because nothing has been realised, so equity IS the base -- a measured fact

Same number, opposite epistemic status. The guard demanded earlier still stands: the writer must not be
able to emit a number it did not measure. The correct move is to record the starting mark WITH its
provenance — that it equals the design base because the route has realised nothing, with the zero closed
trades as the evidence — and datestamp it so profit and loss accumulates on top from then on.

After that single record, the brake is live and everything downstream of it is measured.

---

## AG. The band protects by 0.70 percent — the operator question found it

The operator challenged the seed: why the design base, why not read the broker. The answer held, but my
number was wrong and the challenge exposed something better than the answer.

CORRECTION. I compared against a broker balance of 996,730.93 taken from the LEGACY book, stale since
2026-08-24. The real figure is 251,752.25, from the newest baseline record, status PASS, 2026-09-25
at 18:05 UTC. That account held 1,000,480 in July and 996,730 in August. It has moved by a factor of
four in three months.

The conclusion survives on the corrected figure but with a thinner margin than I implied: four percent of
251,752 is 10,070, and the most all four positions can lose if every stop is hit is 3,817.28, which is
1.52 percent. So seeding from the account would still make the daily arm unreachable — by 2.6 times, not
by 10.

One consequence I checked and it does NOT happen: the exposure caps divide by the account constant, not by
equity, so a high equity mark would not loosen them.

### What the challenge actually found

The band is 10,000 to 250,000, being the base divided by five and times five. The account balance is
251,752.25. The band refuses it by 1,752.25 — 0.70 percent.

So the guard against writing account-scale money into a sleeve equity field is currently working by less
than one percent, against a quantity that has quartered in three months. At 240,000 the broker figure
would pass, the breaker would arm on the wrong scale, and the daily arm would be unreachable again with
everything looking armed and plausible.

And the shape is wrong, not only the number. The edges are a symmetric multiple, which puts the loose
edge on the dangerous side — a mark too large halts spuriously and is visible, a mark too small disarms
silently. The upper edge is anchored to the base, so whether it excludes the account is a coincidence of
where the account sits rather than a property of the rule.

### Why the seed still is the design base

There is no separate pot. The fifty thousand is the capital the strategy was SIZED and VALIDATED against
— one contract per sleeve and seven for stress, chosen from combined drawdown on a fifty-thousand
account, and the walk-forward divides by that same fixed figure. The account holding it has 251,752.

So a sleeve equity can never be OBSERVED, only computed: the base plus this route own realised profit and
loss. The broker mark belongs beside it as reconciliation context, which is the half of the operator
instinct that was right, and it must never flow into the three breaker marks.

Measured anchors now exist for a real upper edge, which the task uses instead of a multiple: the floor
window reproduction ends at 114,902.91 on a 50,000 base, and the two vault windows at 63,236.11 and
58,259.85. Those are the largest legitimate values this route own record has produced.

---

## AH. Today is Sunday and the panel said Today about Friday — 2026-09-27

The operator asked why there was a Nikkei order in Today Decision on a day the market is shut. Traced:

Nothing has run since Friday. Newest window coverage, newest explanations and newest order journal are
all 2026-09-25; there is no record for the 26th or the 27th. The panel selects the snapshot with the
largest date, so it rendered Friday decision — including the Nikkei fill at 01:25 ET Friday, order 40.

The data was right and the provenance line was right: the panel prints the snapshot day in the source
note beside the heading, reading 2026-09-25. The heading was the only thing lying, and it was a
hardcoded string, so it could only ever be correct on a day whose newest snapshot happened to be today.

The lesson is the one the operator demonstrated by tripping over it: having the date on screen SOMEWHERE
is not enough. A reader scans the heading first, which is why a heading may not assert what the data
does not support.

Fixed. The heading now names the day it shows and says plainly when that is not today, using the file own
ET helper that honours the server clock rather than the browser. Selecting the newest snapshot is
unchanged and now asserted in a control test, because showing nothing on a quiet day would be worse than
showing the last day that decided.

Five tests, including one that requires the three cases — today, another day, no day recorded — to render
three DIFFERENT strings, so a fix that collapses two of them fails. Regression: the two DOM suites 110
passed, unchanged.

---

## AI. The slot strip discards the answer that sits in its own row — 2026-09-27

Operator noticed the market view draws slots two ways and one of them is poorer. Measured on the live
session, built through current code:

    NKD      22 slots   17 read unknown
    Swing    23 slots   11 read unknown
    Stress   24 slots    0 read unknown

The lanes above give every slot a truthful state from a six-word vocabulary. The strip beneath has an
eight-word vocabulary and still lands on unknown for 28 slots across two sleeves.

The cause is not missing data. The rows reading unknown carry their outcome in the SAME ROW:

    TRACK1_NKD_0125     reason = shadow_only            candidate_count = 1
    TRACK1_SWING_1510   reason = suppress_same_sleeve   candidate_count = 2

A seven-entry translation table keyed on UPPERCASE words catches everything else in a fallback. The rows
carry lowercase reasons, so the fallback takes them all. The answer is discarded one line before it
would have been displayed.

What is being hidden is worth naming: suppress_same_sleeve is the rule repaired two days ago after
sixteen slots in one night died re-proposing the same trade. It fires, it is recorded, and the page says
unknown.

And the discipline the fix must carry, because it is why this lasted: a fallback that does not name what
it fell back from hides the next gap of the same kind. Unknown must survive and must print the raw word
it did not recognise.

### A separate finding, kept separate

Stress publishes thirteen rule lanes including its actual detector conditions — breadth, gap-down count,
wide count, average gap, stop reference, stop within max percent, target computed. NKD and Swing publish
four, all generic: gate allow, freshness allow, regime lag, admission cap.

So on two of three sleeves the detector own conditions never appear as lanes. That is a gap in what those
sleeves PUBLISH, not in how the page draws, and it belongs to whoever owns those detectors. Written into
the task as report-only so it is not quietly folded into a rendering change.

---

## AJ. Seven lanes read blank, and their reasons blame a rule that passed — 2026-09-27

The operator said seven rows on the Stress tab look empty. The visual complaint is real and the reason
those rows give is worse.

Measured on the live session, through current code. Thirteen lanes over twenty-four slots; six carry
verdicts and seven carry one uniform non-verdict state across all twenty-four cells, in muted and hollow
classes, so they read as blank:

    four setup lanes     not_published x24   "value not published by the detector"
    three admission lanes not_reached  x24   "not reached — the gate stopped the slot first"

And in the SAME payload, two rows above: gate allow passes 24 of 24, freshness allow passes 24 of 24,
while gapdown count and average gap fail 24 of 24.

So three lanes blame the gate for stopping slots the gate let through, with the contradiction on the same
screen. The true cause is in the same thirteen rows: the setup failed at gapdown and at average gap, so
no candidate existed, so the admission rules had nothing to admit and the downstream setup rules were
never computed. All seven rows share that one cause and none of them says it.

Same family as everything else this week — a status branch asserting the story of the case it was written
for. The task requires the sentence to be DERIVED from which rule actually stopped the chain, with a gate
that builds a case where the gate really did stop the slots, so a fix that merely stops mentioning the
gate fails.

### What I got wrong on the way

I assumed twice that the operator was seeing stale code and told them so. Measured: the backend was
restarted at 11:06 today, after the market view change at 10:57, so it is current. And the strip fix from
the previous round is live and working — unknown went from 17 and 11 to zero on NKD and Swing. The thing
the operator was looking at was a different element, which is why I asked instead of guessing a third
time.
