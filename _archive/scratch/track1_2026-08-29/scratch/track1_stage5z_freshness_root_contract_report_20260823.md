# Stage 5Z — freshness semantics, and the shadow writer's root contract

**Session 2026-08-23 · shadow route only · nothing committed**

---

## What the current artifacts implied

Read from disk, not recalled:

- **The 5Y report** left two things open and named both honestly: 91 of 91 accepted
  vault2026 decisions carried a freshness proof marked FAILED, and the writer's bound
  conflicted with the Stage 3 tests' relocated `out_dir`.
- **`run_live_day_track1.py`** computes `fresh.evaluate` in `run_shadow` and puts the result
  in the summary and in the explanation features. **Nothing between that call and
  `run_candidates` consults it.**
- **`track1_freshness.py`** answers about the machine's *current* daily inputs — pre-flight
  record, regime CSV, each parquet — measured against a "required through" session derived
  from the clock.
- **`track1_signal_layer.py`** has seven admission verbs and **not one of them is a freshness
  refusal**, so freshness cannot reject a candidate through the admission path even in
  principle. `run_candidates` takes no freshness argument; `Track1Book.evaluate(cand,
  allow=…)` takes the *breaker's* verdict, not freshness.
- **`OrderGate`** contains **zero** references to freshness — it gates on the blocker
  registry plus `TRACK1_ORDERS_APPROVED`.
- **Stage 3/3B** skips are `TRACK1_EQUIV_FLOOR=1` and `TRACK1_REGEN=1`, both opt-in slow
  tests, neither related to the writer bound.

Taken together: freshness was **reported-only in every mode**, and the records were faithfully
reporting a contradiction the route had always contained.

---

## Part A — freshness semantics audit

### Where it is computed, and where it binds

| Place | Reads freshness? | Binds anything? |
|---|---|---|
| `run_shadow` | yes — `fresh.evaluate(...)` once per run | **no** — result goes to the summary and the records only |
| `explanations_for` | yes — received as a flag | **no** (before 5Z); records it as a proof |
| `run_candidates` / `Track1Book.evaluate` | **no** — no parameter exists | n/a |
| `OrderGate` | **no** — blockers + environment approval only | n/a |
| live slot path (`observe_live_slot`) | binds the **intraday** verdict, a different gate over today's bars | yes, for that gate |

The last row matters: `track1_intraday.validate` (today's bars) **does** bind on the live slot
path. `track1_freshness.evaluate` (daily inputs) binds nowhere. Two different gates, and only
one of them was ever wired.

### Measured counts, before

| Window | Accepted | Freshness proof PASSED | Freshness proof FAILED | Rejected for a freshness reason |
|---|---|---|---|---|
| vault2026 | 91 | **0** | **91** | 0 |
| vault2025 | 128 | **0** | **128** | 0 |

Run-level: `allow=False`, one refusing check (`regime_csv`: last date 2026-08-20, required
2026-08-21), and `intraday_source` reported `unverified`.

### The control that settles it

Same window, same code, three clocks:

```
as_of 2026-08-21 12:00 : run allow=True   accepted=91  freshness-passed=91
as_of 2026-08-21 15:00 : run allow=False  accepted=91  freshness-passed=0
as_of 2026-08-24 09:00 : run allow=False  accepted=91  freshness-passed=0
```

And the same *individual* decision, tracked across those runs:

```
candidate calm_a_atr15_vault2026_MNQ_1, session 2026-01-02, status accepted
explain_id t1x_80d87de4e99c6f2f6b7a14bebfaf22f9   (identical in all three)
  its freshness proof at 12:00 : value=True   passed=True
  its freshness proof at 15:00 : value=False  passed=False
```

**A field that changes while the thing it describes does not is run context, not proof of
that thing.** Worse: it is stored under an identifier that stays constant, so two files
carrying the same `explain_id` could disagree about whether the gate allowed the decision.
That is the same defect family this repository has paid for before — a description that has
walked away from what it describes — arriving inside the record format built to prevent it.

### Mode by mode

| Mode | Reachable today? | Was | Is now |
|---|---|---|---|
| replay source | yes, this is what runs | reported **and cited as proof** | reported as **run context**, never cited as proof |
| shadow live source | the live source still refuses (`NotImplementedError`), so no accepted decision can be produced yet | reported only | **binding** — refuses to record an admission while the gate refused |
| armed / `--allow-orders` | no — the order gate refuses while any blocker is open, and B1 is open | reported only | **binding** |

---

## Part B — the contract chosen

> **Replay** records the freshness verdict as run context and never cites it as a proof of an
> admission. **Shadow live and armed** bind it: a decision may not be accepted while the gate
> refuses, and an accepted record must cite it and show it passed. **In every mode**, an
> accepted decision may not carry *any* proof feature marked FAILED.

Implemented as the smallest change that makes each half enforceable:

1. **`decision_mode` is a required field** — `replay | shadow_live | armed`. A field of its
   own rather than a spelling of `stage`, because `stage` is part of the identifier and a
   field the validator branches on must not also change the id. Schema bumped
   `track1_explain/1 → /2`; nothing had been written to a production path, so the bump costs
   nothing now and would have cost a migration later.
2. **`ACCEPTED_PROOF_RULES_BY_MODE`** replaces the single tuple. Replay owes the cluster cap
   and the breaker; live and armed also owe freshness. The route **derives** its rule set from
   this table rather than holding a second copy.
3. **A new registry rule, `CONTEXT.FRESHNESS_OBSERVED`** — "the gate was read and it bound
   nothing". One run-context `NO_ACTION` record per run carries the real reading. Nothing is
   lost; it is relabelled to what it actually is.
4. **Three validator invariants**, each mutation-checked:
   - an accepted decision carrying any feature with `passed=False` is refused;
   - a replay decision citing `GATE.FRESHNESS` is refused;
   - an unknown or absent `decision_mode` is refused.
5. **`explanations_for` refuses** to build an accepted record in a binding mode when the gate
   refused — raising `FreshnessRefused` rather than downgrading it to a rejection. A candidate
   the engine admitted is not the same thing as one it refused, and writing the second would
   invent a decision that never happened.

No feature value was fabricated and no prose was parsed to recover a number.

### Measured counts, after

| Window | Clock | Decisions | Accepted | Accepted citing FRESHNESS | Accepted w/ failed proof | Context rows | Invalid |
|---|---|---|---|---|---|---|---|
| vault2026 | gate passes | 139 | 91 | **0** | **0** | 1 | **0** |
| vault2026 | gate refuses | 139 | 91 | **0** | **0** | 1 | **0** |
| vault2025 | gate passes | 183 | 128 | **0** | **0** | 1 | **0** |
| vault2025 | gate refuses | 183 | 128 | **0** | **0** | 1 | **0** |

`accepted_with_failed_proof_total` went **91 → 0** on vault2026 and **128 → 0** on vault2025.
The decision stream itself is unchanged: 139 and 183, same identifiers, same statuses. The
freshness reading still differs between clocks — on the context record, which is the one
thing it legitimately describes.

---

## Part C — the writer's root contract

### Audit

- 5Y calls `tx.write_shadow(..., out_dir=<shadow>/explanations/<window>, root=root, mode="w")`,
  once per session date.
- **`root=` is sufficient** for temp-root writes: the bound is computed as
  `<root>/scratch/track1_shadow`, so relocating the root relocates the bound. A temp root
  permits `<tmp>/scratch/track1_shadow` and still refuses `<tmp>/global_index`.
- **The Stage 3 conflict** was never a pytest skip. Those tests aim `out_dir` at an absolute
  temp directory, which the writer cannot know is harmless; 5Y resolved it by recording a
  visible skip in the run summary. That stands, and the two remaining Stage 3/3B skips are
  `TRACK1_EQUIV_FLOOR=1` and `TRACK1_REGEN=1` — opt-in slow tests, **unrelated**.
- **Zero-decision destination resolution** was already fixed in 5Y and is now public rather
  than a reach into a private helper.

### Changes

- **`resolve_shadow_dir()`** — the public form of the bound, so a caller can check the
  destination before building anything.
- **No override flag exists**, and a test reads the signatures of all three path functions to
  prove no `allow_any_path` / `force` / `unsafe` / `bypass` parameter has appeared. A guard
  with an override is a guard that will be overridden.
- **Zero-decision runs report explicitly**: `explanations_written: 0`, `context_records: 1`,
  `rows_written: 1`, `destination_resolved: <path>`. A missing field is a run nobody can tell
  apart from one that never emitted; a zero that is present is a run that had nothing to say.
- **The run-context record is written even at zero decisions.** "The gate was read and said X"
  is a fact about the run, and a run that recorded nothing is indistinguishable from a run
  that never happened.

Refusals verified under a temp root: `global_index`, `monitor`, `monitor/backend`, `.`, `..`,
`scratch`, `scratch/track1_shadow/../../global_index`, `scratch/track1_shadow/../..`,
`../scratch/track1_shadow`, and any absolute path outside the root.

---

## Legacy fingerprint result

**Unchanged.** Nine legacy paths plus every scheduler log, day log and runner-event file are
hashed before and after a shadow run; the fingerprint is asserted non-trivial first so it
cannot pass by covering nothing.

The real `scratch/track1_shadow` was **not written** — every run in this stage used a
relocated temp root, because a parallel session is working in that directory. A test asserts
the real `explanations/` tree does not exist under it.

No monitor file, no dashboard asset and no runtime state file was written.

### A note on the shared file

`global_index/run_live_day_track1.py` is being edited by a parallel session (Stage 5D), which
added a live-slot path at 08:44 while this stage was in progress. Edits here were made
surgically against freshly read regions, and all eight of that session's symbols
(`observe_live_slot`, `close_live_window`, `write_route_checkpoint`, `ShadowRefused` and its
four reason codes) are intact afterwards. This is a genuine two-session collision on one file
and it should not be repeated — the safe pattern is one owner per file per session.

---

## Tests run

```
global_index/test_dashboard_live_snapshot.py
global_index/test_log_hygiene.py
scratch/test_track1_explain_20260823.py               128 passed in 3.94s

scratch/test_track1_explain_wiring_20260823.py         30 passed in 47.78s

scratch/test_track1_stage5z_freshness_root_20260823.py 45 passed in 31.45s   (new)

scratch/test_track1_stage3_route_20260822.py
scratch/test_track1_stage3b_blockers_20260822.py      113 passed, 2 skipped
                                                      (both skips opt-in, unrelated)
```

`global_index/test_event_playback.py` was not run.

### The new guards were mutation-checked

Eleven mutations, one at a time:

| Mutation | Assertion that should fail | Result |
|---|---|---|
| remove "accepted may not carry a failed proof" | live record with failed freshness cannot validate | red |
| remove "replay may not cite the freshness gate" | replay record citing it is refused | red |
| remove the `decision_mode` check | unknown mode / required field | red (2/2) |
| make replay bind freshness (the old contract) | replay is not a binding mode | red |
| stop binding modes refusing (fail-open) | shadow_live refuses an admission while freshness failed | red |
| add an override flag to the bound | no flag switches the bound off | red |
| loosen the bound under a temp root | `global_index` refused / zero-decision legacy aim refused | red (2/2) |
| drop `explanations_written` | zero-decision run reports zero explicitly | red |
| stop emitting the run-context record | zero-decision run still writes it | red |

All restored to green.

---

## Final verdict

**Freshness contract settled?** **Yes.** Replay: run context, never a decision proof — settled
by measurement, not preference, because the same decision reads two different answers under
two clocks three hours apart. Shadow live and armed: binding, and refusing rather than
recording a contradiction.

**Can accepted explanations carry a failed freshness proof?** **No** — in any mode. Refused by
the validator, and the count went 91→0 and 128→0 on the two windows.

**Writer root contract safe?** **Yes.** The bound moves with `root` and there is no flag to
switch it off; nine hostile destinations refused under a temp root; zero-decision runs resolve
the destination and report `explanations_written: 0` explicitly.

**Legacy behaviour changed?** **No.** Fingerprint unchanged, no monitor/dashboard/runtime
write, the real shadow directory untouched.

**Dashboard ready?** **No** — unchanged and untouched by this stage. Track 1 slots remain
invisible to every health signal the monitor has.

---

## Next step

1. **The binding contract is written but has never executed**, because the live source still
   refuses. It is proved by construction — hand-built decisions in each mode — not by a live
   run. That gap should be closed the first time the live source produces a candidate, and
   until then "shadow live binds freshness" is **verified in code, unexercised in the wild**.
2. **`intraday_source` is still reported `unverified`** by the freshness gate in every run.
   That is the honest third state, not a pass, and it is a separate gate from the one settled
   here. Whether an unverified intraday source should block a same-session sleeve is the next
   question of exactly this shape.
3. **Close the three measured feature gaps** (cluster gross, family gross, blocking clusters)
   by capturing the numbers inside the admission loop — an engine change needing its own
   stage and an equivalence test against the current decision stream.
4. **Settle the Stage 5X owner question**: is the empty live decision block on the dashboard a
   design choice or a wiring gap?
5. **One owner per file.** This stage and Stage 5D both edited `run_live_day_track1.py`. It
   came out clean and verified, but that was checked afterwards rather than prevented.
