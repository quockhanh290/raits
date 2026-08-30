# Stage 5ZZZ-AA — quarantining evidence I contaminated

**Route:** `track1_candidate` · **Date:** 2026-08-30 · **Orders:** never enabled, still impossible

**2 rows tainted. 0 deleted. 0 rewritten.** The rows stay on disk; what changed is that every
reader now knows not to believe them.

---

## 1. The contaminated rows

```text
global_index/track1_runtime/signals/track1_signals_20260829.jsonl        2 rows
  session_date 2026-08-29 · roska4_swing · TRACK1_SWING_1405 · 14:05
  mode shadow_live · status SLOT_REFUSED · reason overlap_disagreement

  sha256  8e5f8c0425afc06818e92b7b163e6e216a81c3ab1b9c832aa2e423a297f16b73
          5729c4d2564594bed584efbc6e5608cd5cbab296c73c03ff57def54ac9dd2a7f
```

Written at **21:50:49 machine time (23:50 ET)** by `python -m pytest scratch -q`, the Stage
5ZZZ-Z broad regression run, which started at 21:40:05 and was not output-isolated.

## 2. Proof they were never live slots

Five independent lines, none of which needs the others:

| proof | detail |
|---|---|
| **trading calendar** | 2026-08-29 is a **Saturday**; the repo's own `is_trading_day()` returns `False` |
| **impossible timing** | the row claims `slot_time 14:05` but was written at **23:50 ET**, nine hours later |
| **no scheduler launch** | `TRACK1_SWING_1405` appears **zero** times in `scheduler_0829.log`, and **zero** jobs fired that day |
| **impossible price** | the payload says M2K feed **103.0000** against history **3048.3000** — a fixture value, not a quote |
| **wrong data identity** | `data_source_identity` names the **ES** store while the sleeve is `roska4_swing` on **M2K** |

## 3. The taint record

```text
global_index/track1_runtime/evidence_taint/evidence_taint_20260829.jsonl
  taint_id      5ZZZ-AA-20260830-001
  taint_type    TEST_CONTAMINATION
  source_stage  5ZZZ-Z          created_by_stage  5ZZZ-AA
  action        exclude_from_parity_and_shadow_evidence
  append_only   true            evidence_deleted  0
```

**Rows are matched by the sha256 of their exact stored line**, not by a human-readable
predicate. The predicate is written down too, so a person can see what was tainted without
hashing anything — but a future row matching that predicate is **not** tainted unless its hash
is listed. A predicate could widen onto a legitimate row later; a hash cannot.

### The gap I could not close, stated as a gap

Three `data_observation` files were written in the same window (mtimes 21:50:49, 22:17:10,
21:51:20). Their rows carry their **own historical session dates**, none shows the fixture tell,
and duplicate lines exist — 13 extra in 08-24, 3 in 08-25, 0 in 08-20.

There is no before-snapshot to say whether those duplicates are new. So they are recorded as
**`touched_unproven`** and **not tainted**: marking rows that might be real is the same
falsification in the other direction. This is a measured *"I could not tell"*, not a clean bill
of health.

## 4. What the readers do now

| reader | change |
|---|---|
| `track1_evidence_taint.py` | **new** — three states: `tainted` / `touched` / `clean`. Deliberately not two |
| `track1_replay_parity.py` | `newest_slot()` skips tainted rows; the report surfaces them under `tainted_test_evidence` |
| paper-readiness / audit | **verified unchanged** — 2026-08-29 never entered the judgeable window, so no code change was needed. Asserted by test, not assumed |
| order gate | **untouched** — it does not import the taint module, and a test pins that |

A tainted row is **never scored** — not `PASS`, not `FAIL`. It is not evidence, and scoring it
in either direction would state something about the route.

And it is **surfaced, not hidden**: an excluded row that is invisible is indistinguishable from
a row that never existed.

```text
BEFORE   roska4_swing  FAIL              (from a slot that never ran)
AFTER    roska4_swing  NOT_YET_OBSERVED
         global_nkd / roska4_stress / roska4_calm   NOT_YET_OBSERVED
         tainted_test_evidence  2 rows, TAINTED_TEST_EVIDENCE, never scored
```

## 5. `PAPER_SHADOW_EVIDENCE` is unchanged

```text
judgeable window   2026-08-24 .. 2026-08-28      (2026-08-29 absent)
failing checks     no_failing_days · calm_decision_evidence      — the same two as before
orders_possible    False
```

The contamination never reached the gate. That was luck rather than design — which is why §6
exists.

## 6. Recurrence prevention

`track1_signals.append` now calls `_refuse_production_write_under_pytest`, which fires only when
**both** are true:

- `PYTEST_CURRENT_TEST` is set, **and**
- the destination is inside the `track1_runtime/` tree.

Verified in all four conditions: a test writing to `tmp_path` is allowed, the scheduler (not
under pytest) is allowed, a test writing production is **refused**, and a deliberate integration
write opts in with `TRACK1_ALLOW_RUNTIME_WRITE_IN_TEST=1`.

The guard is narrow on purpose. One that blocks legitimate writes is a guard people learn to
switch off.

`docs/futures/INVARIANTS.md` gained a section carrying the incident, the rule (*tests write to
`tmp_path`; never run all of `scratch/` without isolating output; contaminated evidence is
tainted, never deleted*), and the guard.

## 7. Tests

**19 new, all passing. Six mutations, all caught:** empty taint record, `newest_slot` no longer
skipping tainted rows, tainted evidence scored `PASS`, guard removed, guard too wide (blocking
`tmp_path`), and the predicate widened to everything. **139 regression passed.**

The tests pin both halves — that the rows are **still on disk**, and that they **count for
nothing**.

---

## 8. Answers

| question | answer |
|---|---|
| contaminated rows/files | 2 rows in `track1_signals_20260829.jsonl`, hashes above |
| proof they were not live slots | Saturday · 23:50 ET write for a 14:05 slot · zero scheduler launches · fixture price 103 vs 3048 · wrong data identity |
| taint record path | `global_index/track1_runtime/evidence_taint/evidence_taint_20260829.jsonl` |
| readers that exclude/classify | parity (excludes + surfaces as `TAINTED_TEST_EVIDENCE`); readiness verified unaffected; gate untouched |
| `PAPER_SHADOW_EVIDENCE` unchanged | **yes** — same window, same two failing checks |
| parity false FAIL gone | **yes** — `roska4_swing` back to `NOT_YET_OBSERVED` |
| recurrence prevention | pytest write-guard + `INVARIANTS.md` section |

### Safety

```text
orders_possible          False
blockers                 ['PAPER_SHADOW_EVIDENCE']
orders dir               ABSENT
TRACK1_ORDERS_APPROVED   unset
confirmation             present, STILL GITIGNORED, sha16 67504a1c8a31a6a4
swing paper override     present, valid, grants nothing
broker calls             ZERO
scheduler / backend      NEITHER restarted
runtime evidence deleted 0        runtime evidence rewritten   0
files moved or archived  0
gates changed            NO - the order gate does not import the taint module (pinned by test)
strategy logic · params  unchanged
```
