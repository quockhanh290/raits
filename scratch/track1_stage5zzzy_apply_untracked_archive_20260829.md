# Stage 5ZZZ-Y — the archive applied, and the mistake it nearly repeated

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

**341 files archived. 38 restored. 0 deleted. 0 hash mismatches.**

---

## 1. The mistake, first, because it is the point of the stage

The first sweep moved all 379 approved candidates and **broke three tests**. `pytest
--collect-only` went from the known baseline of **2 errors to 5**.

**Root cause, in my own tool:** the import scan took `m.split(".")[0]`. So
`from scratch.track1_foo import bar` was recorded as an import of **`scratch`** — the real module
name was thrown away. Every dotted submodule import was invisible to it.

The three that broke:

```text
scratch.track1_bootstrap_checkpoint_20260822
scratch.track1_stage5c_shadow_readiness_probe_20260823
scratch.track1_stage5zzzh_swing_d1_regen_20260829
```

**This is the same failure that left `tests/test_raits_vs_hold.py` broken by an unlogged archive
move** — the one Stage 5ZZZ-V found still broken today, and cited as the reason to be careful.
It nearly happened again, in the stage that knew about it. The difference is only that the
brief's own gate caught it: *collection must not gain errors beyond the baseline*, and 5 against
2 is not a pass.

**The fix:** rescan taking **every segment of every dotted import**, plus every filename
appearing in a string literal. That found **38** moved files still referenced. All 38 were
restored to their original paths, hashes verified **38/38**. Collection is back to exactly the
baseline: **4,418 collected, 2 pre-existing errors**.

## 2. Revalidation before touching anything

All 379 plan candidates were rechecked against current reality — the plan predates the Stage
5ZZZ-X commit, which changed the tracked state of 163 files:

```text
path still exists · sha256 matches the plan · destination unique · destination absent
not now tracked · not imported by an active test or source · not linked by a canonical doc
```

**379 approved, 0 skipped.** And the checks were proven non-vacuous: the tracked set was
confirmed non-empty (992 files) and a positive control — `global_index/track1_gates.py` — was
verified present in it, so the "now tracked" test could actually fire.

## 3. What moved

```text
_archive/scratch/track1_2026-08-29/<original relative path>
```

Relative paths preserved, which is what keeps the two `shadow_*_vault2026.jsonl` pairs from
overwriting each other — the collision Stage 5ZZZ-W found.

| classification | moved |
|---|---:|
| `STAGE_REPORT` | 244 |
| `SUPPORTING_PROOF` | 66 |
| `RESEARCH_ONLY` | 13 |
| `REJECTED_RESEARCH` | 12 |
| `GENERATED_TEMP` | 6 |
| **total** | **341** |

Each move was verified the moment it happened — old path gone, new path present, sha256 identical
— with single-file rollback and abort on any failure. **No deletes**; 4.3 MB relocated.

## 4. Validation

```text
missing at archive path       0        hash mismatches               0
old paths still present       0        deletes                       0
tracked files moved           0        test files moved              0
source files moved            0        runtime evidence moved        0
decision records moved        0        canonical docs moved          0
broken canonical links        0        canonical-named paths missing 0
restored files back + intact  38/38
pytest --collect-only         4,418 collected, 2 errors  ==  baseline
```

The decision records are where they belong: `track1_swing_paper_override.json` present and
**tracked** (committed in 5ZZZ-X), `track1_go_live_confirmation.json` present and **still
gitignored**. Runtime evidence and all four B1 files untouched. The module that reads the
override still loads it, and the gate still answers `False`.

## 5. A git-status reading that looks alarming and is not

`git status --short` shows far fewer untracked entries than before. That is not files
disappearing — **`git status` collapses an untracked directory into one line**, so the 342
archived files appear as a single `?? _archive/scratch/track1_2026-08-29/`. At file level:

```text
git ls-files --others --exclude-standard          1,060
  of which under the archive directory              342
archive directory gitignored?                        no
```

I checked, because a count dropping by a third after a file-moving operation is exactly the shape
of a mistake.

## 6. Archive log

`docs/futures/ARCHIVE_LOG.md` gained an entry in the repo's own format: destination, counts,
source plan, a link to the per-file manifest, the keep-policy table, the validation summary, and
an explicit note that **the Track 1 source was committed first** in
`22f6086137519b547e41ba1612f724fad4157ff3` — so that if an archive move ever does break
something, git can now say what changed. It also records the dotted-import lesson, since the
absence of exactly that note is why `raits_vs_hold` is still broken.

---

## 7. Answers

| question | answer |
|---|---|
| candidates in the plan | **379** |
| moved | **341** |
| skipped and why | **38** — restored after the corrected reference scan showed an active test or module still imports them. 0 skipped at revalidation |
| archive root | `_archive/scratch/track1_2026-08-29/<original relative path>` |
| hash preservation | **341/341 moved, 38/38 restored — 0 mismatches** |
| link validation | **0 broken** canonical links, **0** canonical-named paths missing |
| collect-only | **4,418 collected, 2 errors — exactly the baseline, 0 new** |
| git status clean except intended | **Yes** — 3 tracked files modified by this stage (`ARCHIVE_LOG.md`, the pipeline doc, `TASK.md`); the other 33 are pre-existing operator work, untouched |

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
files deleted            NONE
git reset / checkout     NEVER used
archive moves inside the 5ZZZ-X commit   NONE - that commit was source only
strategy logic · params · gates · runtime trading files   unchanged
```
