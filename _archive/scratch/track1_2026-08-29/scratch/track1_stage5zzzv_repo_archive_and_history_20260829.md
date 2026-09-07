# Stage 5ZZZ-V — the archive that did not happen, and the history that did

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

**829 tracked files inventoried. Zero files moved.** The reason is not caution for its own sake —
the stage's premise did not survive its first measurement, and the operator chose the scope once
the real picture was on the table.

---

## 1. The premise did not hold

> *"The working tree contains more than 1,000 tracked files accumulated from Track 1 stages,
> scratch reports, proofs, old baselines, tests, and artifacts."*

Measured with `git ls-files`:

| | |
|---|---:|
| tracked files | **829** |
| tracked files in `scratch/` | **3** |
| of those, Track 1 | **0** |
| untracked files | **1,158** |

The three tracked scratch files are `regime_index_relevance.json`,
`tf_index_proxy_results.json` and `tf_rewfo_qqq_results.json` — stocks/TF research, nothing to do
with Track 1.

**Every Track 1 stage report, the canonical index, the pipeline doc and both decision records are
untracked.** The archive targets the brief describes are, with almost no exceptions, not in git at
all. So "archive stale tracked artifacts" and "archive the Track 1 backlog" turned out to be two
different jobs, and the brief assumed they were one.

## 2. What is actually tracked

| class | count |
|---|---:|
| `ACTIVE_SOURCE` | 383 |
| `UNKNOWN_KEEP` | 126 |
| `ACTIVE_TEST` | 110 |
| `GENERATED_TEMP` *(already under `_archive/`)* | 105 |
| `ACTIVE_DOC` | 40 |
| `RUNTIME_EVIDENCE` | 16 |
| `CANONICAL_DOC` | 3 |
| **deferred archive candidates** | **46** |

The 46 candidates are old stocks/futures one-off diagnostics — `check_*`, `diag_*`, `verify_*`,
`measure_*` — plus stale `.txt`/`.json` reports and a few superseded notes. **None is a Track 1
artifact.**

## 3. A detector bug caught before it moved anything

The first reference scan read `.py`, `.md`, `.json`, `.js` and `.html` — **not `.css`**. So all
**18 `global_index/dash/fonts/*.woff2`** came back as "referenced by nothing" and landed on the
candidate list.

They are referenced, from `global_index/dash/fonts/fonts.css`. Shipping that pass would have
archived the dashboard's entire font set.

It surfaced because the candidate list was *read* rather than trusted: eighteen font files in a
list of stale diagnostics does not look right. Widening the scan to css/txt/yaml/toml/ps1 dropped
the candidates from **63 to 46**.

## 4. The hard-fail guard fired, and I did not disable it

23 of the 46 candidates are top-level one-off `.py` diagnostics. The classifier calls them
`ACTIVE_SOURCE`, and the brief's own rule is *hard fail if active source proposed MOVE*.

The tempting move was to reclassify root scripts so the guard would let them through. That is
precisely the wrong instinct on a stage whose entire purpose is not breaking things, so instead
the judgement went to the operator.

## 5. The operator's decision

**Archive nothing this stage — plan and history only.** And if archiving resumes, use the repo's
existing convention: `_archive/{superseded,answered,dead,docs,scratch}` with a
`docs/futures/ARCHIVE_LOG.md` entry per file, rather than the new dated roots the brief proposed.
A second archive scheme for the same purpose is how future work ends up looking in the wrong
place.

The 46 candidates keep their recorded `sha256_before` in the plan, so if archiving resumes those
hashes are already the before-side of the proof.

## 6. A precedent, found by accident, that argues the same way

Collecting the test suites turns up **two pre-existing errors**:

```text
tests/test_raits_vs_hold.py            ModuleNotFoundError: No module named 'raits_vs_hold'
tests/integration/test_orb_integration.py   raits.backtester.orb_session absent
```

`raits_vs_hold.py` exists — at `_archive/scratch/raits_scripts/raits_vs_hold.py`. **An earlier
archive move broke that test, and it has stayed broken since.** Worse, `ARCHIVE_LOG.md` contains
**zero** mentions of it, so unlike the futures moves that were logged with a reason, a replacement
and a "nothing imports it" verification, this one was never recorded.

Neither error is from this stage — zero files moved, and `git status` shows no deletions or
renames. It is simply the exact failure the reference check and the hard-fail guard exist to
prevent, already sitting in this repo.

## 7. The history report

**`docs/futures/TRACK1_BASELINE_HISTORY_2026-08-29.md`** — 13 sections, from the original
candidate baseline through the runtime split, B1 and legacy retirement, the Calm two-phase
correction, the dashboard diagnostics, the Swing same-day problem, the D-1 reproduction, the
retune and full grid, the rejected SPY/ES proxies, Stage M's parameter translation, the operator
override, the canonical numbers, and what remains before paper.

It publishes **both** Swing figures — cluster P&L (+$18,429 / +$3,906 / −$464) and marginal add
(+$17,382 / +$3,804 / **−$626**) — because Stage 5ZZZ-U found those two being conflated in the
hand-off, and the marginal row is the one that answers "what does Swing add?".

## 8. Validation

**16 tests, all passing.** Since nothing moved, *"nothing moved"* is a claim like any other and is
checked: every path in the plan is still where the plan says, every deferred candidate's hash is
unchanged, and none of the brief's new archive roots exist. The canonical docs cross-link and the
links resolve; no canonical doc claims orders are possible; same-day Swing is still marked not
live-tradable; the Swing identity is still causal D-1 old/effective ema=50.

`pytest --collect-only`: **4,402 tests collected**, 2 pre-existing errors (§6).

---

## 9. Answers

| question | answer |
|---|---|
| tracked files considered | **829** |
| files moved | **0** |
| kept by category | source 383 · unknown-keep 126 · tests 110 · already-archived 105 · docs 40 · runtime evidence 16 · canonical 3 |
| archive roots | **none created** — `_archive/` + `ARCHIVE_LOG.md` if archiving resumes |
| history report | `docs/futures/TRACK1_BASELINE_HISTORY_2026-08-29.md` |
| canonical index | `docs/futures/TRACK1_BASELINE_INDEX_2026-08-29.md` |
| hash verification | 46 candidates hashed; all unchanged, none moved |
| link/test validation | 16/16 passed; 4,402 tests collect; 2 pre-existing errors |
| `UNKNOWN_KEEP` | **126**, kept in place with reasons — the brief's rule when classification is uncertain |

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
runtime trading files touched        NONE
strategy logic · params · gates      unchanged
```

**One thing worth carrying forward.** The two broken tests in §6 are an archive move from before
this stage, unlogged, still broken. If archiving resumes, the `ARCHIVE_LOG.md` discipline — a
reason, a replacement, and a verification that nothing imports it — is not bureaucracy. It is the
thing that would have caught it.
