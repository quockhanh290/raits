# Task: the entry date must survive the dialect, or every stop arms early

LIVE ORDER PATH. This one changes when stops are placed, so the gates matter more than the fix.
Read the whole file before editing. ENGLISH only. No git add or commit. No scheduler or backend
restart. Do not cancel or place any broker order.

---

## 1. What happened, measured this afternoon

The 16:20 ET stop-repair sweep ran and placed a stop behind all four open positions. Two of those
four were not due yet:

    M2K    entered 24/9        arms 25/9 14:00 ET        correct
    MYM    entered 24/9        arms 25/9 14:00 ET        correct
    MNKD   entered 25/9        arms 26/9 01:00 ET        placed about 9 hours early
    MES    entered 25/9 pm     arms 26/9 14:00 ET        placed about 22 hours early

The deferral rule reads a position's entry_day. The route's book writes entry_time and has no
entry_day at all. Measured directly:

    python -c "import json,sys; sys.path.insert(0,'.'); from global_index.runner import _openpos_from_dict; rows=json.load(open('live_positions.track1.json',encoding='utf-8'))['positions']; [print(_openpos_from_dict(r).inst, _openpos_from_dict(r).entry_day) for r in rows]"

    M2K   None
    MYM   None
    MNKD  None
    MES   None

and the rule says, in its own words, that an unknown entry date means "protect, do not guess" and
returns not-deferred -- which arms the stop immediately.

The instinct is right and the direction is wrong for this particular decision. For a stop, arming
early is not the safe side: it changes the strategy's behaviour against the backtest. This repository
has already paid for that exact divergence once -- stops placed at fill instead of the next session,
measured at roughly 53,000 dollars, found and fixed. The dialect gap reintroduced it.

This is the fifth field in the same family. Three were fixed this morning -- inst, contracts,
cluster. entry_day was missed because the specification that authorised that work named only three
fields. That omission is the author's, not yours.

---

## 2. The change

In global_index/runner.py, in the row reader only.

entry_day gains the same two-dialect treatment the other three already have: an explicit entry_day
wins; otherwise derive it from entry_time.

The derivation is the date portion of entry_time, and that is not a shortcut -- it is what the rule
needs. The arming rule takes entry_day, adds a day, and applies 14:00 in the SLEEVE's own timezone.
A Rổ 4 entry_time is ET-naive, so its date part is the ET date. An NKD entry_time carries a Tokyo
offset -- measured on the live book, MNKD's entry_time is 2026-09-25 14:20:00+09:00 -- so its date
part is the Tokyo date. Both are exactly what the rule wants, without converting anything.

There is precedent in this repository for the same derivation: the dashboard's position bridge
already does entry_day from the first ten characters of entry_time. Read it before writing yours.

Do NOT change:

    _stop_deferred            the rule itself, its thresholds, or its None handling
    _ARM_BY_CLUSTER           the per-sleeve arming table
    _openpos_to_dict          see section 4, it is a reporting item, not a change
    anything under global_index/run_stop_repair.py or run_maxhold_exit.py

---

## 3. Gates

**G1** A Track 1 row with an ET-naive entry_time yields the ET date. A Track 1 row with a Tokyo
offset yields the Tokyo date. Assert both with the real values from the live book.

**G2** A legacy row carrying an explicit entry_day is unchanged. Explicit wins over derived.

**G3** A row carrying both, and disagreeing, raises -- the same way the other three dialect fields
do. Assert the message names the field.

**G4 -- the one that must not be quietly flipped.** A row with NEITHER entry_day nor entry_time
still yields None, and _stop_deferred still returns not-deferred for it. That is today's behaviour
on the live path and changing it is a separate decision nobody has taken. Assert it explicitly so
the change cannot drift into it.

**G5 -- the behaviour this exists for.** With the four real book rows and a fixed clock of
2026-09-25 16:30 ET, _stop_deferred returns False for M2K and MYM and True for MNKD and MES. Assert
all four. Two cases would pass with a fix that defers everything.

**G6 -- equivalence.** Every position row in every book and snapshot on disk still loads to
identical values, with one permitted exception: entry_day may go from None to a date on rows whose
entry_time carries one. Nothing else may move. The golden-file approach from the earlier dialect
task applies; rebuild it before you change anything.

**G7 -- no regression.** Baselines measured immediately before this file was written:

    global_index/test_contract_month.py            8 passed
    global_index/test_operational_fixes.py        39 passed
    global_index/test_stp.py                      53 passed
    global_index/test_runner_book_dialects.py     10 passed

Three more cover the rule this change feeds, baselined at the same moment:

    global_index/test_arm_time_per_sleeve.py      19 passed
    global_index/test_stop_deferral.py             3 passed
    global_index/test_stop_placement_time.py       5 passed

All seven must hold. If any of the three moves, stop and report rather than adjusting the test --
those three encode the arming rule itself, and a change that needs them edited is a change to the
rule, which section 2 forbids.

**G8** The live books are not written. Compare the POSITIONS content before and after, not the file
hash: a window close restamps the envelope and changes the hash legitimately.

---

## 4. Two things to MEASURE and report, not change

**4.1 Does the sweep persist the book, and in which shape?** _openpos_to_dict emits the engine's
field names plus the three aliases, and it does NOT emit trade_id, entry_time, risk_dollars, sleeve
or order_id. If the sweep persists through that function, it would strip the route's own fields out
of its book. Measured after today's 16:20 sweep: the four rows still carry all of them, so it did
not persist this time. Find out WHY -- which branch decides -- and report it. Do not change it.

**4.2 What happens to a stop that is already placed when the position becomes deferred?** After this
fix, MNKD and MES read as deferred while each already carries a working STP order placed early. The
next sweep is 18:20 ET. Report what the code does in that case: leaves it, cancels it, or re-places
it. Quote the branch. This decides whether the fix is safe to apply before 18:20 or must wait, and
it is the operator's call once you have reported it.

---

## 5. Files

MODIFY:

    global_index/runner.py                     the row reader only
    new test files you create under global_index/

DO NOT MODIFY: everything else, and in particular the books, anything under
global_index/track1_runtime/, the two sweep entry points, monitor/**, scratch/**, TASK.md,
SCRATCHPAD.md.

---

## 6. Report

    BASELINES        the suites in G7, all seven, before
    GOLDEN           where the golden file is, how many rows, how many changed and how
    CHANGE           the reader diff, quoted
    GATES            G1 to G8, each PASS/FAIL with command and output
    SUITES           all seven, before and after
    MEASURED         4.1 and 4.2, with the branch quoted for each
    NOT DONE         anything left, with the reason
    PLAN PROBLEMS    anything here you believe is wrong, or empty -- and if empty, say you looked
