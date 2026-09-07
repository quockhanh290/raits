# Stage 5ZZZ-A — a signature is not an armed order

**Route:** `track1_candidate` · **Date:** 2026-08-28 · **Orders:** never enabled, still impossible

---

## The answers, first

| question | answer |
|---|---|
| Did Calm 2026-08-28 turn PASS? | **Yes** |
| Did NKD 2026-08-28 turn PASS? | **Yes** |
| Any non-confirmation reason left on those two? | **No** |
| Did `orders_possible` remain false? | **Yes** — `PAPER_SHADOW_EVIDENCE`, throughout |
| Were any runtime trading files touched? | **No** |

```text
                     before                              after
roska4_calm    FAIL  ['confirmation_file_present']  →  PASS  ['all_slots_observed_no_action',
                                                              'no_candidates_to_explain']
global_nkd     FAIL  ['confirmation_file_present']  →  PASS  ['all_slots_observed_no_action']
roska4_stress  FAIL  ['confirmation_file_present',  →  NOT_ENOUGH_DATA_YET ['window_not_closed']
                      'window_not_closed']
roska4_swing   FAIL  (same)                         →  NOT_ENOUGH_DATA_YET ['window_not_closed']
```

Stress and Swing are correct as they stand: their windows open at 10:35 and 14:05 and had not run
when the audit was taken.

---

## The rule, and why it expired

```python
elif confirmation:
    FAIL "the confirmation file exists during a shadow period"
```

When that was written it was true. The signature really was the last thing between this route and
an order, so its presence during a shadow period meant the route could send.

It stopped being true in stages. Stage 5S added a measured evidence gate; Stage 5ZZK gave B1 a
measured half of its own; the operator signed on 2026-08-27 and `orders_possible` never became
true. From then on the file records that a **decision** was made, and whether an order could be
sent is a separate question with its own answer.

The order gate now asks that question directly:

```text
an order mark on any record                    FAIL   (unchanged, and still first)
the gate says orders are possible              FAIL   ← this is the real condition
TRACK1_ORDERS_APPROVED is set                  FAIL   ← new
an order journal directory exists              FAIL   ← new
a signed confirmation, orders still blocked    OK, and says so
```

The last line reads: *"no order marks; B1 confirmation present; orders remain blocked by
PAPER_SHADOW_EVIDENCE"* — reported, not hidden, with the thing that **is** holding orders named
beside it.

The two new FAIL conditions are not decoration. The gate registry deliberately does not read the
environment — Stage 5ZZS pinned that — so without them an approved shadow run would have passed
an audit whose entire subject is whether an order could have been sent.

---

## What the stale rule had been costing

This is the part worth reading twice.

**It was masking real failures.** On 2026-08-27 the audit recorded `['confirmation_file_present']`
and nothing else for all four sleeves. Re-evaluated with the rule removed:

| sleeve | what was actually wrong on 2026-08-27 |
|---|---|
| `global_nkd` | `checkpoint_wrong_day` |
| `roska4_calm` | `coverage_incomplete`, `slot_could_not_evaluate`, `no_candidates_to_explain` |
| `roska4_stress` | `coverage_incomplete`, `slot_could_not_evaluate` |
| `roska4_swing` | `checkpoint_wrong_day` |

Anyone reading that day's record would have seen one stale-policy reason and moved on. **Four
sleeves had real problems underneath it.** 2026-08-27 still FAILS after this change, and it
should — for those reasons, which are now visible.

**And it was feeding the only remaining blocker.** `PAPER_SHADOW_EVIDENCE` counts failing days:

```text
shadow_evidence → False
  judgeable_days:  4 judgeable day(s) on record, 5 required
  no_failing_days: 4 FAIL day(s) in the qualifying window, at most 0 allowed
```

A rule that fails every day from the signature onward does not merely make noise — it manufactures
the failures that hold the route's last gate shut.

---

## The audit records on disk

Task 4 asked for an append-only corrected record if the pattern allows. **I did not append one**,
and the reason is measured rather than cautious:

- **2026-08-28** — the audit jobs run at 03:05, 10:10, 12:40, 16:05 and 16:15 ET and will write
  corrected rows today from the fixed code. A hand-written row would carry my pid and an invented
  `audit_trigger`, which is not what any other row in that file means.
- **2026-08-27** — re-evaluating gives **FAIL either way**. A "corrected" row would state the same
  verdict with different reasons, so appending one changes no count and no decision.

The stored rows stay as a true record of what the audit said under the old policy. Nothing was
rewritten or deleted.

---

## Tests

| | |
|---|---|
| New suite | **18 passed** |
| Adjacent suites | **460 passed**, 3 failed |
| Mutations | **9/9 caught** |
| Caused by this change | **0** — measured by reverting the branch chain and diffing |

Because this stage **removed** a FAIL, most mutations re-arm the route some other way and require
the suite to notice: orders genuinely possible, the approval marker set, an order journal on disk,
an order mark on a record. Two put the stale rule back.

Two mutations came back green before they were right, and both were honest verdicts. One dropped
`possible` from `possible or not blocking` — inert, because the fixture flipped both facts
together and the two are coupled in practice; a test that flips each alone now covers it. The
other forced the `window_not_closed` branch false and fell through to an `else` producing the same
code.

### Stale tests restated while passing

Six tests across five suites still asserted the pre-B1 world — the same family Stage 5ZZS
restated in four suites and 5ZZW in two more. Four asserted the confirmation file does not exist;
they now assert that the things which **arm** an order do not exist, and that any decision on disk
is signed. Two pinned the exact blocker roster, which changes with record age and with evidence.

The 3 remaining failures were measured as not caused here and belong to two other families:
parquet fingerprints and dates pinned against a store that has since grown, and fixtures written
before Stage 5ZZC changed how the SPY refresh calls `_run`. Both want their own stage.

---

## Safety

```text
orders_possible            False          track1_blocking ['PAPER_SHADOW_EVIDENCE']
scheduler                  pid 3000, not restarted        broker  not connected
track1_go_live_confirmation.json          intact and signed — not deleted
track1_runtime/orders                     ABSENT          live_positions.track1.json  ABSENT
TRACK1_ORDERS_APPROVED                    unset
strategy · schedule · gates · order send  untouched — this stage changed audit semantics only
```

`TRACK1_ORDERS_APPROVED` appears in one test, set through `monkeypatch` inside the test process
and asserted to make the audit **FAIL**. It is never written to a file, never exported, and is
restored automatically — the opposite of arming anything.

Only `global_index/track1_shadow_acceptance.py` changed in production code.

---

## Still open

- **2026-08-27 fails for four real reasons** now visible for the first time — two checkpoints on
  the wrong day, and coverage gaps on Calm and Stress. Worth a stage of its own; this one only
  removed what was hiding them.
- `PAPER_SHADOW_EVIDENCE` still reports 4 judgeable days of 5 and 4 failing days. The failing
  count will not move for 08-27, which fails on merit; 08-28 should stop counting once today's
  scheduled audits write their corrected rows.
- The Calm window in the audit's own table still reads `["10:00","10:00"]`, from before Calm
  became two phases. Coverage passes anyway — "2 of 1 decided" — but the expected count is stale.
- The two unrelated test families above.
