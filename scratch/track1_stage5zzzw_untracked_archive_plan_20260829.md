# Stage 5ZZZ-W — the untracked archive plan, and a finding that outranks it

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

**1,220 untracked files inventoried. 635 are Track 1. 379 are move candidates. Zero files moved.**

The plan is below. But the most important thing this stage found is not about archiving.

---

## 1. The Track 1 route is not in version control

```text
global_index/track1_*.py     tracked: 0      untracked: 40
git log --all -- "global_index/track1_*.py"  ->  empty
```

**Never committed. Not on this branch, not on any branch.** That includes
`global_index/track1_gates.py` — the order gate itself — along with `track1_live_source.py`,
`run_live_day_track1.py`, `track1_normal_r4.py` and the rest of the live route. Also uncommitted:
`monitor/backend/track1_market_view.py`, `track1_runtime_reader.py`, the four
`global_index/track1_b1/*.jsonl` B1 evidence files, and `track1_swing_paper_override.json`.

### This is not the same as the things that are ignored on purpose

Two Track 1 paths *are* deliberately kept out of git, and `.gitignore` says why:

```text
:211  track1_go_live_confirmation.json   "the file that ARMS the route, so it must never be
                                          something a checkout can create"
:215  global_index/track1_runtime/       "append-only runtime output measured in megabytes"
```

Those are design decisions with reasons attached. The 40 source files are not — they were simply
never added. The two cases are distinguishable because `git ls-files --others --exclude-standard`
already excludes ignored files, so anything it lists is *not* ignored; each was then confirmed
with `git check-ignore`.

**And there is an inconsistency worth naming:** the confirmation record is deliberately ignored
and documented. The swing paper override sitting beside it is *neither* ignored *nor* committed.
Two decision records, two different treatments, and only one of them looks intended.

### What it costs

- The live order gate has no version history at all.
- The Stage 5ZZZ-Q and 5ZZZ-T edits to safety files have **no committed baseline to diff
  against**. That is not hypothetical: Stage 5ZZZ-T could not use git to attribute a regression
  and had to neutralise the change at runtime instead, because `git show HEAD:<file>` answered
  *"exists on disk, but not in HEAD"*.
- The B1 evidence and the signed override exist only on this disk.

**I have not fixed this.** Committing the live route is a decision with real consequences and it
should not ride along inside a cleanup stage. It is measured, raised, and left to the operator.

## 2. The inventory

| | count |
|---|---:|
| untracked total | **1,220** |
| Track 1 | **635** |
| non-Track 1 | 585 |
| **MOVE_CANDIDATE** | **379** |
| KEEP | 290 |
| IGNORE_NON_TRACK1 | 551 |

Track 1 breakdown:

| classification | action | count |
|---|---|---:|
| `STAGE_REPORT` | MOVE_CANDIDATE | 274 |
| `SUPPORTING_PROOF` | MOVE_CANDIDATE | 74 |
| `RESEARCH_ONLY` | MOVE_CANDIDATE | 13 |
| `REJECTED_RESEARCH` | MOVE_CANDIDATE | 12 |
| `GENERATED_TEMP` | MOVE_CANDIDATE | 6 |
| `TEST_ARTIFACT` | KEEP | 112 |
| `UNKNOWN_KEEP` | KEEP | 82 |
| `ACTIVE_SOURCE` | KEEP | 43 |
| `SUPPORTING_PROOF` | KEEP | 6 |
| `RUNTIME_EVIDENCE` | KEEP | 4 |
| `CANONICAL_DOC` | KEEP | 3 |
| `STAGE_REPORT` | KEEP | 5 |
| `DECISION_RECORD` | KEEP | 1 |

## 3. Two hazards the plan caught before anything moved

**An active test imports a module on the move list.** Two of them:

```text
scratch/test_track1_presleep_readiness_20260824.py  ->  track1_presleep_readiness_20260824
scratch/test_track1_stage5m0_state_repair_20260823.py -> track1_stage5m0_state_repair_20260823
```

This is precisely how `tests/test_raits_vs_hold.py` was broken by an earlier archive sweep and has
stayed broken ever since. Both are now `KEEP`, and the classifier protects **any** module an
active test imports.

**A basename collision in a flat archive directory.** `shadow_decisions_vault2026.jsonl` and
`shadow_settlements_vault2026.jsonl` each appear twice under different directories. Flattening
them into one archive folder would have had one file **silently overwrite the other** — data loss,
not merely a broken link. The proposed archive path now preserves each file's relative path.

Neither would have been visible without doing the plan first. That is the argument for the
plan-only rule, made concrete.

## 4. Archive convention

```text
_archive/scratch/track1_2026-08-29/<original relative path>
```

The repo's existing convention, per `docs/futures/ARCHIVE_LOG.md` and the operator's Stage 5ZZZ-V
decision. No new archive root is invented. Each move needs an `ARCHIVE_LOG.md` entry carrying a
reason, a replacement and a "nothing imports it" verification — the discipline whose absence is
why `raits_vs_hold` is still broken.

## 5. Validation gates — 0 failures

```text
every untracked Track 1 file appears in the plan     PASS
canonical doc as MOVE_CANDIDATE                      0
decision record as MOVE_CANDIDATE                    0
runtime evidence as MOVE_CANDIDATE                   0
active test as MOVE_CANDIDATE                        0
active (uncommitted) source as MOVE_CANDIDATE        0
candidates missing a sha256                          0
destination collisions                               0
active tests importing a candidate                   0
files moved                                          0
```

## 6. High-risk files kept

- **43 uncommitted Track 1 source files** — kept, and flagged in §1.
- **4** runtime/B1 evidence files · **1** decision record · **3** canonical docs · **112** active
  tests.
- **10** kept because a canonical document links them, including
  `scratch/track1_stage5zzzn_canonical_strategy_baseline_reproduction_20260829.json` and the
  Stage 5ZZZ-H remeasure the index calls out by name.
- **82 `UNKNOWN_KEEP`** — kept with the reason recorded, per the brief's uncertainty rule.

---

## 7. Is a second apply stage safe?

**Yes for the 379 candidates, under three conditions:**

1. **Re-verify each `sha256` immediately before and after the move.** The hashes in this plan are
   from 2026-08-29 and `scratch/` keeps changing as work continues.
2. **Write an `ARCHIVE_LOG.md` entry per file**, including the "nothing imports it" check.
3. **Re-run `pytest --collect-only` afterwards** and compare against the current baseline of
   **4,402 collected with 2 known pre-existing errors**. Any *new* error means something on the
   list was still needed.

**Not safe as part of a cleanup:** committing the 40 uncommitted Track 1 source files. That is a
version-control decision, not an archive one, and it deserves its own stage.

### Safety

```text
orders_possible          False
blockers                 ['PAPER_SHADOW_EVIDENCE']
orders dir               ABSENT
TRACK1_ORDERS_APPROVED   unset
confirmation             present, untouched, grants no order authority
swing paper override     present, valid, grants nothing
broker calls             ZERO
scheduler / backend      NEITHER restarted
files moved/deleted/renamed          NONE
git reset / checkout                 NEVER used
strategy logic · params · gates      unchanged
```
