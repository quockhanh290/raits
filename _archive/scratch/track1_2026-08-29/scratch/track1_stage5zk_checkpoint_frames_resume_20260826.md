# Stage 5ZK — the checkpoint stops recording nothing

**2026-08-26, ET 00:28–01:05.** No orders · no confirmation file · `TRACK1_ORDERS_APPROVED`
unset · no `--allow-orders` · **nothing restarted** · no manual edit to any runtime checkpoint,
book or audit record · no strategy, rule, cap or backtest-identity change.

```text
UTC 2026-08-26 05:05 · ET 2026-08-26 01:05 EDT · Calgary 2026-08-25 23:05 MDT · Tokyo 14:05 JST
```

*Two of the read-first paths do not exist under the names given:
`track1_stage5zj_make_5zg_live_20260825.md` is dated `20260826` (written after ET midnight),
and there is no `track1_stage5q9_identity_match_20260824.md` — the nearest artefacts are
`test_track1_stage5q9_identity_admission_20260824.py`, `_track1_stage5q9_sizing_basis.json`
and `track1_stage4b_identity_liveframe_report_20260823.md`, which is what was read.*

---

## The ten answers

| | |
|---|---|
| 1. any real runtime checkpoint/book/audit changed? | **no** — both artefacts still at 13:56:19, the Part A baseline |
| 2. is the live checkpoint still quiet/empty, and valid? | **yes and yes** — the book proves route, day and zero positions |
| 3. will entries be usable when the book has open positions? | **yes** — measured: 5 of 5 entries return `Resumed`, and a position survives the round trip |
| 4. frames reused or reloaded? | **reloaded** — and the reason is narrower than it first looked (§3) |
| 5. measured cost and headroom? | **6.0–6.2 s** for the whole write; **221 s** of headroom under the 300 s ceiling |
| 6. does it fail closed on an open book with no entries? | **yes** — `checkpoint_entries_missing_for_open_book`, and the mirror case too |
| 7. strategy/backtest identity unchanged? | **yes** — identity hashes identical before and after, asserted both directions |
| 8. orders still impossible? | **yes** |
| 9. next shadow window still READY? | **yes** — NKD opens 01:10 ET, four minutes after this was written |
| 10. what remains, and is 5ZL next? | five items; **yes, 5ZL** |

---

## 1. Part A — the baseline

```text
scheduler pid 18096   backend pid 30604   track1-only-shadow   orders_possible False
blocking  B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE
```

| artefact | state |
|---|---|
| `replay_checkpoint.track1.json` | 13:56:19, 315 B — schema 2, one route, four sleeves, **0 instrument entries** |
| `live_positions.track1.json` | 13:56:19, 284 B — route `track1_candidate`, cut `2026-08-25T15:55:01-04:00`, **0 positions**, equity 0 |
| `window_coverage/`, `slot_timing/`, `audits/` | present |
| `trade_log.track1.jsonl` | 22:20:01, 0 B — Stage 5ZJ's writability probe |

So the runtime checkpoint is quiet and empty, no Track 1 position has ever existed, and under
the quiet-window contract the empty checkpoint is **valid**: the book proves the route, the day
and that nothing was held.

---

## 2. Part B — what the closing slot actually has

The checkpoint is written from one production call site, and it passes no frames. The obvious
question was whether the slot already holds what it needs.

**It does, and they are not the parquets.** `observe_live_slot` builds
`src.sleeve_frames(...)[sleeve]` — the *joined* frames, parquet history with today's broker
bars spliced on — and `JoinedFrame` keeps only the joined result. Those frames are in scope at
the close and are dropped at the function's return boundary, before the writer runs.

### The measurement that decided the design

The naive fix is to load the parquets and fingerprint them through the cut day. Measured on the
live store, that does not work, and the reason is in the data:

```text
MES  parquet: newest day 2026-08-25 last bar 13:44   |  previous day 2026-08-24 last bar 23:59
MNKD parquet: newest day 2026-08-25 last bar 13:45   |  previous day 2026-08-24 last bar 23:59
```

The daily append runs at 13:45 ET. At a 15:55 close the store holds today only to 13:44, while
yesterday is complete to 23:59 — so **the next append backfills today's afternoon**, and those
bars sit *below* the cut a fingerprint through today would use. Simulated on both instruments:

```text
fingerprint through the NEWEST stored day, after the next append:  changed
fingerprint through the PREVIOUS day,      after the next append:  unchanged
```

A checkpoint naming the cut day would therefore be refused by every later resume, with
`fingerprint_rowcount` — a code that reads like data corruption. So the entry must name the
last **complete** day, derived from the frame rather than from the clock.

### Cost, measured on the real store

| | load | fingerprint | rows |
|---|---:|---:|---:|
| M2K | 0.14 s | 0.50 s | 2,952,425 |
| MES | 0.11 s | 0.56 s | 3,371,008 |
| MNKD | 0.11 s | 0.29 s | 2,043,688 |
| MNQ | 0.10 s | 0.53 s | 3,358,539 |
| MYM | 0.10 s | 0.54 s | 3,315,419 |

All five: **2.67 / 2.90 / 2.98 s** (min/median/max, three runs). The whole
`write_route_checkpoint`, including the identity hashes: **5.97 / 6.16 / 6.22 s**.

Against a 300 s slot ceiling and a Swing p95 of 78.5 s, that is **2 % of the budget**, and it
lands on **one** slot per sleeve because the checkpoint is written at the close. The closing
Swing slot goes from 78.5 s to about **84.7 s**; headroom **221 s**.

---

## 3. A claim of mine the data corrected mid-stage

I wrote, in code and in a test, that the frames already in the slot's memory were *the wrong
ones* — that splicing changes the hash, so reuse would produce a checkpoint refusing every
resume. The test written to prove it **went green instead of red**, and it was right to.

That claim is true through the **cut day** and false through the **last complete day**: the
appended live bars sit above the cut, so both frames hash the same prefix. Measured per
instrument, both directions:

```text
fingerprint(spliced, last_complete_day) == fingerprint(parquet, last_complete_day)   all 5
fingerprint(spliced, cut_day)           != fingerprint(parquet, cut_day)             all 5
```

So **reuse would have worked.** Reloading is a choice, and the honest reasons are:

- the parquet is what the resume path reads, so fingerprinting it *is* the contract, rather
  than being equal to it by an argument about what the join does and does not touch;
- the closing slot holds only its own sleeve's instruments — `sleeve_frames` is called with one
  sleeve — so reuse would checkpoint four instruments at the Swing close and one at the NKD
  close, never all five from one place;
- 6 s against 221 s of headroom buys the simpler seam and leaves `observe_live_slot`'s return
  shape alone.

Both the source comment and the test now say this. The test that was going to prove reuse
impossible instead pins that it is merely unnecessary — and it goes red the day the join starts
rewriting history below the cut, which is the day the choice stops being a preference.

---

## 4. What changed in the writer

- `last_complete_day(df)` — the newest day the parquet has stopped filling, derived from the
  frame's own day index, returned tz-naive because `fingerprint` requires it.
- `checkpoint_frames(data_paths)` — loads the five cross-day parquets and reports by name any
  it could not, rather than raising. A checkpoint writer must not be able to stop a window from
  closing.
- `write_route_checkpoint`: `frames=None` now means **load them**; `frames={}` means
  *deliberately none*. They used to mean the same thing, and that is exactly how the production
  call site — which passes neither — wrote an empty checkpoint on every window for as long as
  the route has been running.
- Its return value now carries `entry_count`, `instruments`, `last_day_by_inst` and
  `frames_unavailable`, so a caller printing that line can tell an empty checkpoint that was
  *correct* from one that was empty because a frame did not load. `sleeves` alone could not.
- `track1_bootstrap.checkpoint_entries` takes an optional `last_day_by_inst`. Omitted, it uses
  the cut day exactly as before, so the bootstrap path — which has always been handed complete
  history — is byte-identical, asserted.

Measured end to end, into a temp root:

```text
entry_count       0  ->  5
instruments       ['M2K', 'MES', 'MNKD', 'MNQ', 'MYM']
last_day_by_inst  all 2026-08-24
resume check      5 of 5 Resumed, 0 refused
```

---

## 5. Part C — the acceptance contract

| condition | verdict |
|---|---|
| complete window, no positions, empty entries, book proves route/day/flat | **OK** |
| complete window, open position, entries with a position | **OK** |
| complete window, **open position, no entries** | **FAIL** `checkpoint_entries_missing_for_open_book` |
| entries carry a position, book says flat | **FAIL** `checkpoint_book_disagrees_with_entries` |
| incomplete window | never asked for a checkpoint at all |
| schema-1 flat payload | **FAIL** `checkpoint_unreadable` — and `route_checkpoint.load` refuses it too |
| route is not `track1_candidate` | **FAIL** `checkpoint_wrong_route`, naming what it did find |
| book missing / undated / unreadable | **FAIL** `checkpoint_day_unverifiable` |
| entries dated after the judged day | **FAIL** `checkpoint_wrong_day` |
| entries more than 5 days behind | **FAIL** `checkpoint_history_stale` |

### Stage 5ZH's entry-day rule is replaced, and why

5ZH said: when entries exist, their `last_day` must equal the judged day, and the book is not
consulted. The first half is disproved by the measurement above — a correct entry names the
*previous* trading day — so that rule would have failed every real checkpoint the writer can
produce, including the first one it ever produced.

The replacement is simpler than the split rule it replaces: **the book is the day proof in both
cases**, because it is written in the same call, atomically beside the checkpoint. What the
entries are still asked is that their history is not from the future and not stale. Six tests
in the 5ZH suite were rewritten to the new contract, each carrying the reason.

The open-book guard is the part that protects a case the route has never reached and will reach
the first day it holds something overnight: a restart resuming flat against a book that is not
is the resume-a-state-that-never-existed failure the whole identity machinery exists to prevent.

**Re-judged read-only against the live evidence, nothing moved:** the checkpoint check still
returns OK for the quiet artefact, `roska4_swing` 2026-08-25 still PASSes, and Calm, Stress and
NKD still fail on their own grounds.

---

## 6. What this stage did *not* fix

The route has no cross-day book. `observe_live_slot` builds a fresh `Track1Book` per slot and
never loads the persisted one, and `write_route_checkpoint` synthesises a state with
`positions: []` when no `book_state` is handed to it. So today's book is not a book — it is a
correctly-shaped "nothing is held" marker, and it is accurate only because nothing is held.

That means the open-position path is **built and tested but not reachable in production**: the
writer will record a position when given one, and nothing gives it one. Making the route carry
a book across slots is position lifecycle, which is 5ZN's subject, not a checkpoint change.

The fail-closed guard is what stands in the gap until then, and it is the right thing to stand
there: the day a position exists and the checkpoint does not record it, the audit says so
instead of passing.

---

## 7. Tests

**38 tests**, `scratch/test_track1_stage5zk_checkpoint_frames_resume_20260826.py`. Every
checkpoint is produced by the real writer and read by the real reader; every frame is a real
parquet, read-only, because the one claim a fixture cannot support is a runtime-budget claim —
a synthetic frame would load in milliseconds and prove nothing about 3.4 million rows. The
budget test asserts the frames it timed are over a million rows each, so it cannot pass on a
toy.

All nine items the brief lists, plus the branches the measurement suggested: the derived day
survives the next append while the newest day does not, per instrument; a same-length repair
still changes the hash; a checkpoint that named the cut day is refused after an append (the
rule not adopted, kept as a live counterfactual); `frames=None` and `frames={}` differ; the
writer records what it could not load; the identity hash is unchanged by writing a checkpoint
and is the same hash that lands in the entry; and `checkpoint_frames` imports no signal, rule
or gate module, checked by AST rather than by reading it.

---

## 8. Part E — liveness

**No restart, and none needed.** Every changed module is imported by a *subprocess*: the
scheduler spawns `python -m global_index.run_live_day_track1` for slots and `_run(argv)` for the
audits. Both pick up current source on their next launch. The dashboard reader was not touched,
so the backend is unaffected.

The next Track 1 window opens at 01:10 ET, four minutes from this writing, and its close at
02:55 will be the first to run the new writer. Restarting the scheduler ten minutes before a
window opens would have been the wrong trade for no gain.

---

## 9. Regression

| | |
|---|---|
| Stage 5ZK | **38 passed** |
| checkpoint and acceptance surface (5ZK, 5ZH, 5Q, 5Q1, 5Q2, 5Q3, 5P, route-checkpoint stage 1, bootstrap stage 2, 5D, 5E, 5F, dashboard wiring, 5ZG, 5ZF) | **572 passed, 1 skipped, 2 failed** |

Six failures were the absence-proxy pattern in the three suites that exercise
`write_route_checkpoint` — this stage's own function, so in surface — and were repaired the same
way as their four predecessors: mtime instead of absence, with the reason recorded. Sixth
occurrence of that pattern.

Two remain, both pre-existing and neither this stage's surface: a default-mode job count of 61
against a pinned 60, and a blocker set that gained `PAPER_SHADOW_EVIDENCE` after the suite was
written. Both were already classified in 5ZI.

**Newly surfaced, pre-existing, not fixed here.** `test_every_engine_params_built_in_production_states_its_fill_law`
fails on `track1_signals.py:224`, which builds `NormalR4Params()` without naming a fill law.
That file is Stage 5ZD's and its mtime is twelve hours older than any edit here. The
construction is diagnostics-only — it reads configured thresholds to record them in the signal
journal and decides nothing — so the risk is narrow: if the default ever diverged, the journal
would print a threshold the decision path does not use. It belongs with the sleeve rule-exposure
work, not with a checkpoint change.

---

## 10. What remains before paper, and what is next

| | item | class |
|---|---|---|
| 1 | machine sleep | **operator** |
| 2 | B1 — separate account or a proven-flat legacy book | **operator decision** |
| 3 | regime verification warn-only, and its return discarded | **5ZL** |
| 4 | route-aware P&L, open-position parity, legacy-reader split | **5ZM** |
| 5 | planned stop not journalled; `close_position` and `place_protective_stop` unbuilt; no cross-day book | **5ZN** |

**Removed:** *"the checkpoint cannot resume anything"*. It can, measured, five entries out of
five — with the caveat in §6 that the position half is unreachable until 5ZN gives the route a
book to carry.

**Next is 5ZL**, and it is the smallest thing left. Three answers instead of two, `UNKNOWN`
failing closed, and the result reaching the exit status so a drift becomes a child failure the
journal can show. It needs no broker, no frames and no restart, and until it lands a label
drift is invisible from end to end — logged as a warning nobody reads, returning a number the
one call site discards, in a job that exits 0.

---

## 11. Files changed

| file | change |
|---|---|
| `global_index/run_live_day_track1.py` | `last_complete_day`, `checkpoint_frames`, `frames=None` now loads, richer return |
| `global_index/track1_bootstrap.py` | optional `last_day_by_inst`; default path byte-identical |
| `global_index/track1_shadow_acceptance.py` | book is the day proof always; open-book guard; three new codes and reasons; `CHECKPOINT_MAX_HISTORY_LAG_DAYS` |
| `scratch/test_track1_stage5zk_…py` | new, 38 tests |
| `scratch/test_track1_stage5zh_…py` | section C rewritten to the corrected contract |
| `scratch/test_track1_stage5d/5e/5f_…py` | six absence proxies moved to mtime |

**No runtime file was written or edited.** `replay_checkpoint.track1.json` and
`live_positions.track1.json` both still carry 13:56:19 — exactly the Part A baseline —
and no audit record was rewritten.
