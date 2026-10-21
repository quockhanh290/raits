# Task V2: the entry DATE, in three parts — supersedes the V1 spec

V1 asked for one change and set two gates that cannot both pass. The refusal to implement it was
correct and is the reason this file exists. Read section 0 before anything else.

LIVE ORDER PATH. ENGLISH only. No git add or commit. No scheduler or backend restart. Do not place
or cancel a broker order.

---

## 0. What V1 got wrong, and the three things now known

**V1's premise was validated against the wrong rows.** The derivation "entry_day is the first ten
characters of entry_time" was checked against M2K and MYM. Those two rows were written by a
back-fill script, by hand, with a full timestamp. They are not what the live writer produces.

Measured on the four rows actually in the book:

    M2K   roska4_swing   entry_time '2026-09-24 15:55:00'          back-filled by hand
    MYM   roska4_swing   entry_time '2026-09-24 15:55:00'          back-filled by hand
    MNKD  global_nkd     entry_time '2026-09-25 14:20:00+09:00'    written live, carries a date
    MES   roska4_swing   entry_time '15:00'                        written live, NO date at all

So V1's G5 demanded MES read as deferred while G6 forbade inventing a date for it. Both were right;
the specification was wrong.

**The root is upstream.** global_index/track1_normal_r4.py line 722 builds the swing setup with

    entry_time=str(pd.Timestamp(bar_ts).time())[:5]

It takes a full bar timestamp and keeps only HH:MM. Nothing downstream can recover the date.

**An already-placed stop is safe.** Measured and reported: deferred positions are excluded from the
only branch that inspects or places a stop, and there is no cancellation branch anywhere. So making
MNKD and MES read as deferred will NOT cancel the early stops already working on them. It only
prevents further placement attempts. This work can therefore land at any hour; there is no overnight
exposure created by applying it.

**One correction to V1 in the other direction, from the report.** V1 claimed the writer omits
risk_dollars and sleeve. It does not — it emits both, sleeve because an alias for it was added that
morning. It strips trade_id, entry_time and the route's order_id. That matters: if any path ever
persists through that writer, entry_time is the field it destroys, which is the field this whole
task exists to preserve. Treat that as a latent hazard, not as today's bug.

---

## Part 1 — stop discarding the date upstream

The swing setup keeps the full timestamp instead of a clock string.

**The risk that makes this more than a one-line change:** something may already consume entry_time
as a bare HH:MM. Find every consumer before changing the producer, and list them in your report.
Display code, sorting, parsing, comparisons, tests, and anything that slices or formats it.

If a consumer genuinely needs the clock form, do not force the change on it — give it the clock from
the full value at the point of use. Changing a producer without checking its consumers is how the
qty defect and the dialect defects were introduced.

### Gates

**P1.1** A swing setup produced by the live path carries a date-bearing entry_time.
**P1.2** Every consumer found in your survey still behaves identically. Assert each one you found;
if there are none, say you looked and how.
**P1.3** The NKD path is untouched — it already carries a dated, offset-aware value, and it must come
through byte-identical.

## Part 2 — the reader derives a date, and refuses to guess

entry_day gains the two-dialect treatment: an explicit entry_day wins, otherwise derive from a
date-bearing entry_time.

A bare clock is NOT a date. When entry_time carries no date, entry_day stays None and the deferral
rule keeps answering not-deferred — today's behaviour, unchanged. Do not use trade_id as a fallback
date source: it carries the reference day, which coincides with the entry date on all four current
rows and is not the same quantity. Coinciding today is not a guarantee.

What must change is that the gap becomes visible rather than silent. A position whose deferral cannot
be computed must be reportable as such; propose where that surfaces and why, without building it into
a file you were not given.

### Gates

**P2.1** A dated entry_time yields its date. Assert both an ET-naive value and the Tokyo-offset value
from the live book.
**P2.2** A bare clock yields None, and _stop_deferred still returns not-deferred for it. This is the
assertion that keeps the fix from guessing.
**P2.3** An explicit entry_day wins over a derived one.
**P2.4** Both present and disagreeing raises, as the other three dialect fields do.
**P2.5 — revised from V1, which could not pass.** Against a fixed clock of 2026-09-25 16:30 ET and
the four real rows: M2K and MYM read due, MNKD reads deferred, and MES reads NOT DEFERRED because its
row carries no date. Assert all four, and assert MES's reason is the absent date rather than a
computed verdict. After Part 3 repairs that row, MES flips to deferred and this gate is updated —
say so in your report rather than pre-empting it.
**P2.6** Equivalence: every position row in every book and snapshot on disk still loads to identical
values, except entry_day, which may only go from None to a date on rows whose entry_time carries one.
Rebuild the golden set; assert it is non-empty before comparing.

## Part 3 — repair the MES row. REPORT ONLY, do not write.

The MES row can be repaired without guessing: the order journal holds ref_day 2026-09-25 and
created_at 2026-09-25T19:07:02+00:00 for that fill.

Propose the exact repaired value and say which source you took it from and why that source is the
entry date rather than something adjacent to it. Do NOT write to the book — live position state is
the operator's, and every book repair this week has gone through them with a snapshot first.

---

## Files

MODIFY:

    global_index/track1_normal_r4.py      part 1, the setup builder only
    global_index/runner.py                part 2, the row reader only
    new test files under global_index/, named with the prefix test_entrydate_

DO NOT MODIFY: the books, anything under global_index/track1_runtime/, the sweeps,
run_live_day_track1.py, track1_signal_layer.py (another task is live on those two), monitor/**,
scratch/**.

## Baselines, measured before this file was written

    global_index/test_contract_month.py            8 passed
    global_index/test_operational_fixes.py        39 passed
    global_index/test_stp.py                      53 passed
    global_index/test_runner_book_dialects.py     10 passed
    global_index/test_arm_time_per_sleeve.py      19 passed
    global_index/test_stop_deferral.py             3 passed
    global_index/test_stop_placement_time.py       5 passed

The last three encode the arming rule itself. If any of them moves, stop and report rather than
editing the test: a change that needs them edited is a change to the rule, which this task forbids.

## Report

    CONSUMER SURVEY   part 1: every consumer of entry_time you found, and what you did about it
    CHANGE            both edits, quoted
    GATES             P1.1 to P1.3 and P2.1 to P2.6, each PASS or FAIL with command and output
    SUITES            all seven, before and after
    PART 3            the proposed MES value, its source, and why that source is the entry date
    BOOK              positions content before and after, not the file hash
    NOT DONE          anything left, with the reason
    SPEC PROBLEMS     anything here you believe is wrong, or empty — and if empty, say you looked
