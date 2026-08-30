# Stage 5ZZZ-Z — post-archive regression: the archive is clean

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

**No failure in this stage is attributable to the archive.** Collection matches the baseline
exactly, every archived file is present with its hash intact, and the Track 1 core suites are
green apart from one 2026-08-27 assertion that the archive could not have touched.

---

## 1. Baseline state before any test

```text
branch          future/incorporation
HEAD            22f6086  Track 1 route source and baseline records
archive root    _archive/scratch/track1_2026-08-29/   342 files
ARCHIVE_LOG     Stage 5ZZZ-Y entry present
canonical links 0 broken · 0 canonical-named paths missing
orders_possible False   blockers ['PAPER_SHADOW_EVIDENCE']
orders dir      ABSENT   approval env unset
scheduler 34564 ALIVE, not restarted
```

## 2. Targeted archive / canonical suites — 42 passed, 6 failed

Stage 5ZZZ-X and 5ZZZ-Y have **no test suites** — one was a commit, the other a move. That gap is
named rather than glossed; their guarantees are verified directly in §6 instead.

All six failures are **`STALE_TEST`**: tests pinning a pre-action state that a later *authorised*
stage deliberately changed. Each was confirmed from its assertion text, not assumed:

| test | evidence | why |
|---|---|---|
| 5ZZZ-V `plan covers every tracked file` | `assert 829 == 992` | 5ZZZ-X committed 163 files after the plan was written |
| 5ZZZ-W `plan covers every untracked file` | 346 absent, all under the archive root | the archived files are new paths that did not exist then |
| 5ZZZ-W `no destination exists yet` | `_archive/…/_track1_stage5q1_mutations.json` exists | the apply stage was authorised to create them |
| 5ZZZ-W `every planned source path still exists` | **341** planned paths gone | exactly the 341 the manifest records as moved |
| 5ZZZ-W `no archive dir was created` | the directory exists | created by the apply stage |
| 5ZZZ-W `finding matches what git says` | *"track1 source is now tracked — update the plan"* | **the test fired because the problem it described was fixed** |

That last one is worth pausing on. It was written to go red the moment the version-control finding
was resolved. Stage 5ZZZ-X resolved it. The test is working exactly as designed, and its failure
is the signal, not the fault.

## 3. Track 1 core suites — 270 passed, 1 failed

Eleven suites: canonical baseline, Swing override, replay parity, live Swing causal D-1, restart
liveness, dashboard performance, gate AST memoization, paper account baseline, B1 operator
decision, B1 confirmation recognition, market-view UI contract.

The single failure is `test_19_orders_are_still_impossible_and_nothing_was_armed`, and its name
demands a close look. **Its three order-safety assertions all pass:**

```python
assert possible is False          # PASSES
assert blocking                   # PASSES
assert not Path(".../orders").exists()   # PASSES
assert not Path("track1_go_live_confirmation.json").exists()   # <- fails here
```

It fails only on the *absence* of the confirmation file — a suite written **2026-08-27** asserting
a file the operator signed at **10:05 that same day**. `PRE_EXISTING`, and it cannot be
archive-caused: the file's mtime is 2026-08-27 and its sha16 has not changed all session.

**Orders remain impossible. The assertions that check that are green.**

## 4. Collect-only versus baseline

```text
python -m pytest --collect-only -q scratch/ tests/ monitor/
  4,418 collected · 2 errors        baseline: 4,418 · 2      MATCH
```

Both errors are the known pre-existing pair — `test_raits_vs_hold` (broken by an earlier
**unlogged** archive move) and `test_orb_integration`.

**A framing error I caught in myself:** a bare `pytest --collect-only -q` reports **1,004**, not
4,418. That is a different scope, not a regression — the baseline was measured with an explicit
path list, and the comparison has to use the same command. Reporting 1,004 against 4,418 would
have manufactured an alarming number out of nothing.

## 5. Classification

| class | count |
|---|---:|
| **`NEW_FROM_ARCHIVE`** | **0** |
| `STALE_TEST` | 6 |
| `PRE_EXISTING` | 1 |
| `FLAKY_ORDER_DEPENDENT` · `ENVIRONMENTAL` · `UNKNOWN` | 0 |

**No failing test was edited or re-pinned.** Each is reported with its cause, following the rule
held since Stage 5ZZZ-R: re-pinning asserts the new values are correct, and that is the operator's
call.

## 6. No side effects

```text
runtime trading files modified   0      orders dir created       False
approval env set                 False  broker calls             ZERO
scheduler restarted              No     backend restarted        No
archive files deleted            0      archived files present   341/341
archived hash mismatches         0      restored files intact    38/38
```

The four runtime trading files show clean in `git status` — tracked and unmodified since the
commit.

---

## 7. Verdict

**The archive is safe.** Every failure is explained and none is archive-caused: six tests pin a
state that authorised later stages changed on purpose, and one predates the archive by two days.
Collection is identical to the baseline, and all 341 archived files plus all 38 restored files are
present and hash-verified.

### Safety

```text
orders_possible          False
blockers                 ['PAPER_SHADOW_EVIDENCE']
orders dir               ABSENT
TRACK1_ORDERS_APPROVED   unset
confirmation             present, STILL GITIGNORED, sha16 67504a1c8a31a6a4
swing paper override     present, TRACKED, valid, grants nothing
broker calls             ZERO
scheduler / backend      NEITHER restarted
files moved or deleted this stage        NONE
git reset / checkout                     NEVER used
strategy logic · params · gates          unchanged
```
